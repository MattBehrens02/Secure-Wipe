from datetime import datetime, timezone
import os
import time

from modules.app_logging import log_error, log_info
from modules.terminal import WipeCommands, run_command


def _humanize_step_name(step_name: str) -> str:
    """Convert snake_case step names to Title Case for display."""
    return " ".join(word.capitalize() for word in step_name.split("_"))


class WipeEngine:
    """Orchestrates a single-drive cryptographic wipe workflow.

    The workflow is intentionally linear and runs each step in a fixed order.
    All command execution is funneled through `_run_step_command` so dry-run
    behavior is centralized in one place.
    """

    drive: object
    path: str
    dry_run: bool

    def __init__(self, drive, dry_run: bool = False):
        """Initialize wipe engine state for one selected drive."""
        self.drive = drive
        self.path = drive.path  # /dev/sdx
        self.dry_run = dry_run
        self.smart_before = getattr(drive, "smart_data", None)
        # Temporary key file used only for this wipe session.
        self.keyfile = "/tmp/securewipe.key"
        # Device-mapper name used when opening the LUKS container.
        self.mapping_name = f"wipe_{self.path.split('/')[-1]}"

    def execute(self):
        """Run the full wipe sequence and return a high-level status result."""
        started_at = datetime.now(timezone.utc).isoformat()
        total_start_perf = time.perf_counter()
        failed_step = None
        error_message = None
        mapping_open = False
        step_durations_seconds: dict[str, float] = {}

        try:
            failed_step = "generate_temporary_key"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._generate_temporary_key()
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "create_luks2_container"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._create_luks2_container()
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "open_encrypted_container"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._open_encrypted_container()
            mapping_open = True
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "write_across_encrypted_drive"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._write_across_encrypted_drive()
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "close_encrypted_container"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._close_encrypted_container()
            mapping_open = False
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "destroy_luks2_container"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._destroy_luks2_container()
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            failed_step = "remove_residual_signatures"
            step_start = time.perf_counter()
            log_info(f"Starting wipe step={failed_step} drive={self.path}")
            self._remove_residual_signatures()
            step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

            if getattr(self.drive, "is_hdd", False):
                failed_step = "final_hdd_overwrite"
                step_start = time.perf_counter()
                log_info(f"Starting wipe step={failed_step} drive={self.path}")
                self._final_hdd_overwrite()
                step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)
            else:
                print("[INFO] Skipping final HDD overwrite since drive is not detected as HDD.")
                log_info(f"Skipping final_hdd_overwrite drive={self.path} reason=not_hdd")

            status = "dry_run" if self.dry_run else "success"
            failed_step = None

        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            print(f"[ERROR] Wipe failed at step '{failed_step}': {error_message}")
            log_error(f"Wipe failed drive={self.path} step={failed_step} error={error_message}")

        finally:
            cleanup_errors = []

            if mapping_open:
                try:
                    cleanup_step_start = time.perf_counter()
                    self._close_encrypted_container()
                    step_durations_seconds["cleanup_close_encrypted_container"] = round(
                        time.perf_counter() - cleanup_step_start, 3
                    )
                except Exception as exc:
                    cleanup_errors.append(f"close_encrypted_container: {exc}")

            try:
                cleanup_step_start = time.perf_counter()
                self._delete_temporary_key()
                step_durations_seconds["cleanup_delete_temporary_key"] = round(
                    time.perf_counter() - cleanup_step_start, 3
                )
            except Exception as exc:
                cleanup_errors.append(f"delete_temporary_key: {exc}")

            finished_at = datetime.now(timezone.utc).isoformat()
            total_duration_seconds = max(0.001, round(time.perf_counter() - total_start_perf, 3))

            if cleanup_errors:
                cleanup_text = "; ".join(cleanup_errors)
                if error_message:
                    error_message = f"{error_message}; cleanup_errors={cleanup_text}"
                else:
                    error_message = f"cleanup_errors={cleanup_text}"
                if status != "failed":
                    status = "failed"
                    failed_step = "cleanup"
                log_error(f"Wipe cleanup issue drive={self.path} details={error_message}")

        if status != "failed":
            log_info(
                f"Wipe finished drive={self.path} status={status} started_at={started_at} finished_at={finished_at}"
            )

        return WipeResult(
            status=status,
            drive_path=self.path,
            started_at=started_at,
            finished_at=finished_at,
            failed_step=failed_step,
            error_message=error_message,
            duration_seconds=total_duration_seconds,
            step_durations_seconds=step_durations_seconds,
            smart_before=self.smart_before,
        )

    def _run_step_command(self, cmd, info_message: str):
        """Execute one command or print it when running in dry-run mode."""
        if self.dry_run:
            print("[DRY RUN]", " ".join(cmd))
            log_info(f"dry_run_command drive={self.path} cmd={' '.join(cmd)}")
            return

        print(info_message)
        log_info(f"run_command drive={self.path} cmd={' '.join(cmd)}")
        run_command(cmd, check=True)

    def _generate_temporary_key(self):
        """Create random key material used to format/open a temporary LUKS container."""
        cmd = ["dd", "if=/dev/urandom", f"of={self.keyfile}", "bs=1M", "count=4"]
        self._run_step_command(cmd, "[INFO] Generating temporary keyfile...")

    def _create_luks2_container(self):
        """Format the target drive as a LUKS2 container using the temporary key."""
        cmd = WipeCommands.luks_format(self.path, self.keyfile)
        self._run_step_command(cmd, "[INFO] Creating LUKS2 container...")

    def _open_encrypted_container(self):
        """Open the LUKS container to expose a writable mapper device path."""
        cmd = WipeCommands.luks_open(self.path, self.keyfile, self.mapping_name)
        self._run_step_command(cmd, "[INFO] Opening encrypted container...")

    def _write_across_encrypted_drive(self):
        """Overwrite the mapped encrypted block device using scrub."""
        mapped_device = f"/dev/mapper/{self.mapping_name}"
        cmd = WipeCommands.scrub(mapped_device, pattern="nnsa")
        self._run_step_command(cmd, "[INFO] Scrubbing mapped device...")

    def _close_encrypted_container(self):
        """Close the LUKS mapper to detach the encrypted view of the drive."""
        cmd = WipeCommands.luks_close(self.mapping_name)
        self._run_step_command(cmd, "[INFO] Closing encrypted container...")

    def _destroy_luks2_container(self):
        """Erase LUKS metadata/header so the temporary encryption key path is gone."""
        cmd = WipeCommands.destroy_luks_header(self.path)
        self._run_step_command(cmd, "[INFO] Destroying LUKS2 header...")

    def _remove_residual_signatures(self):
        """Remove any remaining filesystem signatures from the raw device."""
        cmd = WipeCommands.wipefs(self.path)
        self._run_step_command(cmd, "[INFO] Removing residual filesystem signatures...")

    def _final_hdd_overwrite(self):
        """Perform a final overwrite of the entire drive with zeros (HDD-specific)."""
        cmd = WipeCommands.scrub(self.path, pattern="fillzero")
        self._run_step_command(cmd, "[INFO] Performing final HDD overwrite...")

    def _delete_temporary_key(self):
        """Best-effort cleanup of the temporary wipe key file."""
        if self.dry_run:
            print(f"[DRY RUN] rm -f {self.keyfile}")
            log_info(f"dry_run_cleanup drive={self.path} keyfile={self.keyfile}")
            return

        try:
            os.remove(self.keyfile)
            log_info(f"Removed temporary keyfile drive={self.path} keyfile={self.keyfile}")
        except FileNotFoundError:
            return

    def verify(self):
        """Placeholder for post-wipe verification logic."""
        raise NotImplementedError("Use verify(app_config) for post-wipe verification.")

    def verify_with_config(self, app_config):
        """Run post-wipe verification using the configured verification policy."""
        from modules import verification

        return verification.verify_wipe(
            self.drive,
            app_config,
            dry_run=self.dry_run,
            smart_before=self.smart_before,
        )


class WipeResult:
    """Minimal result object returned by WipeEngine.execute."""

    def __init__(
        self,
        status: str,
        drive_path: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        failed_step: str | None = None,
        error_message: str | None = None,
        duration_seconds: float | None = None,
        step_durations_seconds: dict[str, float] | None = None,
        smart_before: dict | None = None,
        verification_result: object | None = None,
    ):
        self.status = status
        self.drive_path = drive_path
        self.started_at = started_at
        self.finished_at = finished_at
        self.failed_step = failed_step
        self.error_message = error_message
        self.duration_seconds = duration_seconds
        self.step_durations_seconds = step_durations_seconds or {}
        self.smart_before = smart_before
        self.verification_result = verification_result

    def format_duration_summary(self) -> str:
        """Format duration metrics as human-readable output."""
        if not self.duration_seconds:
            return ""

        lines = [f"Duration summary: {self.duration_seconds}s total"]
        for step_name, duration in self.step_durations_seconds.items():
            human_name = _humanize_step_name(step_name)
            lines.append(f"  {human_name}: {duration}s")

        return "\n".join(lines)