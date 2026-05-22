from datetime import datetime, timezone
import os
import sys
import time
import uuid

from modules.app_logging import log_error, log_info
from modules import recovery
from modules.terminal import WipeCommands, run_command


def _humanize_step_name(step_name: str) -> str:
    """Convert snake_case step names to Title Case for display."""
    return " ".join(word.capitalize() for word in step_name.split("_"))


def _format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0.0, float(seconds))
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _clean_info_label(info_message: str) -> str:
    label = info_message.strip()
    if label.startswith("[INFO]"):
        label = label[len("[INFO]") :].strip()
    if label.endswith("..."):
        label = label[:-3].strip()
    return label


def _spinner_frame(elapsed_seconds: float) -> str:
    frames = ["|", "/", "-", "\\"]
    frame_idx = int(max(0.0, elapsed_seconds) / 0.25) % len(frames)
    return frames[frame_idx]


def _build_progress_line(
    *,
    step_index: int,
    step_total: int,
    step_label: str,
    elapsed_step: float,
    overall_elapsed: float,
    eta_hint: float | None,
    bar_width: int = 20,
) -> str:
    ratio = None
    if eta_hint is not None:
        total_estimate = elapsed_step + max(0.0, eta_hint)
        if total_estimate > 0:
            ratio = min(0.999, max(0.0, elapsed_step / total_estimate))

    if ratio is None:
        spinner = _spinner_frame(elapsed_step)
        bar = "[" + ("." * bar_width) + "]"
        pct_text = " --%"
        activity = f"{spinner} running"
    else:
        filled = int(ratio * bar_width)
        bar = "[" + ("#" * filled) + ("-" * (bar_width - filled)) + "]"
        pct_text = f" {int(ratio * 100):>3}%"
        activity = "running"

    return (
        f"Step {step_index}/{step_total} {step_label} "
        f"{bar}{pct_text} {activity} "
        f"step {_format_seconds(elapsed_step)} "
        f"total {_format_seconds(overall_elapsed)} "
        f"ETA {_format_seconds(eta_hint)}"
    )


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
        self._overall_start_perf = 0.0
        self._avg_step_seconds: float | None = None
        self._remaining_steps_after_current = 0
        self._step_progress_emit_interval = 15.0
        self._last_step_progress_emit = 0.0
        self._current_step_index = 0
        self._current_step_total = 0
        self._current_step_label = ""

    def execute(self):
        """Run the full wipe sequence and return a high-level status result."""
        return self._execute_internal(recovery_state=None, state_dir=None)

    def execute_with_recovery(self, app_config):
        """Run wipe with checkpoint persistence and resume support."""
        recovery_cfg = getattr(app_config, "recovery", object())
        state_dir = getattr(getattr(app_config, "paths", object()), "state_dir", "./state")
        resume_max_age_seconds = int(getattr(recovery_cfg, "resume_state_max_age_seconds", 86400))
        allow_failed_resume = bool(getattr(recovery_cfg, "allow_failed_resume", False))
        max_resume_attempts = int(getattr(recovery_cfg, "max_resume_attempts", 3))

        drive_serial = str(getattr(self.drive, "serial", "") or "").strip() or None
        state = recovery.load_state(state_dir, self.path, drive_serial=drive_serial)
        resumed_from_checkpoint = False
        resume_source_status = None

        if state and recovery.should_offer_resume(
            state,
            max_age_seconds=resume_max_age_seconds,
            allow_failed_resume=allow_failed_resume,
        ):
            if not hasattr(state, "metadata") or not isinstance(state.metadata, dict):
                state.metadata = {}
            if not getattr(state, "session_id", ""):
                state.session_id = str(uuid.uuid4())
            resumed_from_checkpoint = True
            resume_source_status = state.status
            state.max_resume_attempts = max_resume_attempts
            state.increment_resume_attempts()
            state.metadata["resumed"] = True
            state.metadata["resume_source_status"] = resume_source_status
            log_info(
                f"Recovery resume accepted drive={self.path} resume_attempts={state.resume_attempts}"
            )
        else:
            state = recovery.RecoveryState(
                session_id=str(uuid.uuid4()),
                drive_path=self.path,
                mapping_name=self.mapping_name,
                keyfile_path=self.keyfile,
                max_resume_attempts=max_resume_attempts,
            )
            state.metadata["resumed"] = False
            log_info(f"Recovery new session drive={self.path} session_id={state.session_id}")
            state.metadata["drive_name"] = getattr(self.drive, "name", "")
            state.metadata["drive_model"] = getattr(self.drive, "model", "")
            state.metadata["drive_vendor"] = getattr(self.drive, "vendor", "")
            state.metadata["drive_serial"] = getattr(self.drive, "serial", "")
            state.metadata["drive_size"] = getattr(self.drive, "size", "")
            state.metadata["drive_type"] = getattr(self.drive, "type", "")
            state.metadata["drive_mountpoints"] = list(getattr(self.drive, "mountpoints", []) or [])
            state.metadata["drive_removable"] = bool(getattr(self.drive, "removable", False))
            state.metadata["drive_transport"] = getattr(self.drive, "transport", "")
            state.metadata["drive_rotational"] = getattr(self.drive, "rotational", None)
            state.metadata["drive_media_type"] = getattr(self.drive, "media_type", "Unknown")
            state.metadata["drive_is_hdd"] = bool(getattr(self.drive, "is_hdd", False))
            state.metadata["drive_smart_data"] = getattr(self.drive, "smart_data", None)

        recovery.save_state(state_dir, state)
        result = self._execute_internal(recovery_state=state, state_dir=state_dir)

        if result.status in {"success", "dry_run"}:
            state.mark_completed()
            recovery.save_state(state_dir, state)
            recovery.clear_state(state_dir, self.path, drive_serial=drive_serial)
        else:
            if state.status == "in_progress":
                state.mark_interrupted(result.error_message)
                recovery.save_state(state_dir, state)

        result.recovery_resumed = resumed_from_checkpoint
        result.recovery_session_id = getattr(state, "session_id", None)
        result.recovery_resume_attempts = int(getattr(state, "resume_attempts", 0) or 0)
        result.recovery_state_status = getattr(state, "status", None)
        result.recovery_resume_source_status = resume_source_status

        return result

    def _execute_internal(self, recovery_state=None, state_dir=None):
        """Run the wipe sequence with optional recovery checkpoint integration."""
        started_at = datetime.now(timezone.utc).isoformat()
        total_start_perf = time.perf_counter()
        self._overall_start_perf = total_start_perf
        failed_step = None
        error_message = None
        mapping_open = False
        step_durations_seconds: dict[str, float] = {}

        use_recovery = recovery_state is not None and state_dir is not None
        preserve_key_on_failure = bool(use_recovery)

        steps = [
            ("generate_temporary_key", self._generate_temporary_key),
            ("create_luks2_container", self._create_luks2_container),
            ("open_encrypted_container", self._open_encrypted_container),
            ("write_across_encrypted_drive", self._write_across_encrypted_drive),
            ("close_encrypted_container", self._close_encrypted_container),
            ("destroy_luks2_container", self._destroy_luks2_container),
            ("remove_residual_signatures", self._remove_residual_signatures),
        ]
        if getattr(self.drive, "is_hdd", False):
            steps.append(("final_hdd_overwrite", self._final_hdd_overwrite))
        else:
            print("[INFO] Skipping final HDD overwrite since drive is not detected as HDD.")
            log_info(f"Skipping final_hdd_overwrite drive={self.path} reason=not_hdd")

        resume_from_index = 0
        if use_recovery:
            completed_step_names = [
                entry.split(":", 1)[1]
                for entry in recovery_state.step_history
                if isinstance(entry, str) and entry.startswith("done:")
            ]
            if completed_step_names:
                last_completed = completed_step_names[-1]
                for idx, (name, _func) in enumerate(steps):
                    if name == last_completed:
                        resume_from_index = idx + 1
                        break

            # Mapper open/close semantics require replay from open step when
            # resuming in the middle of mapped-device operations.
            step_names = [name for name, _ in steps]
            if "open_encrypted_container" in step_names and "close_encrypted_container" in step_names:
                open_index = step_names.index("open_encrypted_container")
                close_index = step_names.index("close_encrypted_container")
                if open_index < resume_from_index <= close_index:
                    resume_from_index = open_index

            if resume_from_index > 0:
                log_info(f"Recovery resuming drive={self.path} from_step_index={resume_from_index}")
                print(f"[INFO] Resuming wipe at step index {resume_from_index} for {self.path}")

        try:
            for idx, (step_name, step_func) in enumerate(steps):
                if idx < resume_from_index:
                    continue

                completed_step_count = len(step_durations_seconds)
                self._avg_step_seconds = (
                    (sum(step_durations_seconds.values()) / completed_step_count)
                    if completed_step_count > 0
                    else None
                )
                self._remaining_steps_after_current = max(0, len(steps) - (idx + 1))
                eta_hint = None
                if self._avg_step_seconds is not None:
                    eta_hint = self._avg_step_seconds * (self._remaining_steps_after_current + 1)

                self._current_step_index = idx + 1
                self._current_step_total = len(steps)
                self._current_step_label = _humanize_step_name(step_name)

                print(
                    f"[PROGRESS] Step {idx + 1}/{len(steps)}: {_humanize_step_name(step_name)} "
                    f"(elapsed={_format_seconds(time.perf_counter() - total_start_perf)}, "
                    f"est_remaining={_format_seconds(eta_hint)})"
                )

                failed_step = step_name
                if use_recovery:
                    recovery_state.mark_step_started(step_name)
                    recovery.save_state(state_dir, recovery_state)

                step_start = time.perf_counter()
                log_info(f"Starting wipe step={failed_step} drive={self.path}")
                step_func()

                if failed_step == "open_encrypted_container":
                    mapping_open = True
                elif failed_step == "close_encrypted_container":
                    mapping_open = False

                step_durations_seconds[failed_step] = round(time.perf_counter() - step_start, 3)

                if use_recovery:
                    recovery_state.mark_step_completed(step_name)
                    recovery.save_state(state_dir, recovery_state)

            status = "dry_run" if self.dry_run else "success"
            failed_step = None

        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            print(f"[ERROR] Wipe failed at step '{failed_step}': {error_message}")
            log_error(f"Wipe failed drive={self.path} step={failed_step} error={error_message}")
            if use_recovery:
                recovery_state.mark_interrupted(error_message)
                recovery.save_state(state_dir, recovery_state)

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

            if not (preserve_key_on_failure and status == "failed"):
                try:
                    cleanup_step_start = time.perf_counter()
                    self._delete_temporary_key()
                    step_durations_seconds["cleanup_delete_temporary_key"] = round(
                        time.perf_counter() - cleanup_step_start, 3
                    )
                except Exception as exc:
                    cleanup_errors.append(f"delete_temporary_key: {exc}")
            else:
                log_info(f"Preserving temporary keyfile for resume drive={self.path} keyfile={self.keyfile}")

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
                if use_recovery:
                    recovery_state.mark_failed(error_message)
                    recovery.save_state(state_dir, recovery_state)

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

        self._last_step_progress_emit = 0.0
        rendered_progress = False

        def _emit_progress(elapsed_step: float) -> None:
            nonlocal rendered_progress
            if elapsed_step - self._last_step_progress_emit < self._step_progress_emit_interval:
                return

            self._last_step_progress_emit = elapsed_step
            overall_elapsed = time.perf_counter() - self._overall_start_perf

            eta_hint = None
            if self._avg_step_seconds is not None:
                remaining_current = max(0.0, self._avg_step_seconds - elapsed_step)
                eta_hint = remaining_current + (self._avg_step_seconds * self._remaining_steps_after_current)

            line = _build_progress_line(
                step_index=self._current_step_index,
                step_total=self._current_step_total,
                step_label=self._current_step_label or _clean_info_label(info_message),
                elapsed_step=elapsed_step,
                overall_elapsed=overall_elapsed,
                eta_hint=eta_hint,
            )

            sys.stdout.write("\r" + line.ljust(140))
            sys.stdout.flush()
            rendered_progress = True

        try:
            run_command(cmd, check=True, progress_callback=_emit_progress)
        finally:
            if rendered_progress:
                sys.stdout.write("\n")
                sys.stdout.flush()

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
        recovery_resumed: bool = False,
        recovery_session_id: str | None = None,
        recovery_resume_attempts: int = 0,
        recovery_state_status: str | None = None,
        recovery_resume_source_status: str | None = None,
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
        self.recovery_resumed = recovery_resumed
        self.recovery_session_id = recovery_session_id
        self.recovery_resume_attempts = recovery_resume_attempts
        self.recovery_state_status = recovery_state_status
        self.recovery_resume_source_status = recovery_resume_source_status

    def format_duration_summary(self) -> str:
        """Format duration metrics as human-readable output."""
        if not self.duration_seconds:
            return ""

        lines = [f"Duration summary: {self.duration_seconds}s total"]
        for step_name, duration in self.step_durations_seconds.items():
            human_name = _humanize_step_name(step_name)
            lines.append(f"  {human_name}: {duration}s")

        return "\n".join(lines)