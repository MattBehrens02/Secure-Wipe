import datetime
import os
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from modules.terminal_ui import CommandRunnerError, CommandRunnerTimeout, run_command


@dataclass
class WipeStepResult:
    """Per-step execution record used for auditing and recovery integration."""

    name: str
    status: str
    started_at: str
    finished_at: str
    command: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    message: str | None = None


@dataclass
class WipeResult:
    """Top-level wipe result payload returned by WipeEngine.execute."""

    device_path: str
    status: str
    steps: list[WipeStepResult]
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_path": self.device_path,
            "status": self.status,
            "steps": [asdict(step) for step in self.steps],
            "failure_reason": self.failure_reason,
        }


class WipeEngine:
    """Runs the secure wipe workflow for one selected device.

    Notes for maintainers:
    - All external process calls are routed through modules.terminal_ui.run_command.
    - Dry-run mode records simulated steps but skips destructive commands.
    - Cleanup must always run; key material is removed in execute() finally block.
    """

    def __init__(
        self,
        device_path: str | Any,
        media_type: str = "Unknown",
        app_config: Any | None = None,
        algorithm: str = "scrub",
    ):
        # Support both call styles:
        # 1) WipeEngine("/dev/sdb", media_type="HDD", ...)
        # 2) WipeEngine(drive_obj, ...), where drive_obj has .path and optional .media_type
        if hasattr(device_path, "path"):
            drive_obj = device_path
            resolved_path = str(getattr(drive_obj, "path"))
            resolved_media_type = str(getattr(drive_obj, "media_type", media_type))
        else:
            resolved_path = str(device_path)
            resolved_media_type = media_type

        self.device_path = resolved_path
        self.media_type = resolved_media_type
        self.algorithm = algorithm
        self.app_config = app_config

        self.steps: list[WipeStepResult] = []
        self.key_file_path: str | None = None
        self.mapping_name = f"swipe_{Path(resolved_path).name}_{secrets.token_hex(4)}"

        self.dry_run = bool(getattr(getattr(app_config, "runtime", object()), "dry_run", True))
        self.command_timeout = int(getattr(getattr(app_config, "wipe", object()), "command_timeout_seconds", 600))
        self.temp_dir = str(getattr(getattr(app_config, "paths", object()), "temp_dir", "/tmp"))
        self.mount_mode = str(getattr(getattr(app_config, "safety", object()), "mount_handling_mode", "deny")).lower()

    @staticmethod
    def _utc_now() -> str:
        return datetime.datetime.now(datetime.UTC).isoformat()

    @staticmethod
    def _excerpt(value: str | None, limit: int = 300) -> str | None:
        if not value:
            return None
        trimmed = value.strip()
        if len(trimmed) <= limit:
            return trimmed
        return f"{trimmed[:limit]}..."

    def _record_step(
        self,
        name: str,
        status: str,
        started_at: str,
        command: list[str] | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        message: str | None = None,
    ) -> None:
        # Keep result shape stable so reporting/recovery can consume it later.
        self.steps.append(
            WipeStepResult(
                name=name,
                status=status,
                started_at=started_at,
                finished_at=self._utc_now(),
                command=" ".join(command) if command else None,
                stdout_excerpt=self._excerpt(stdout),
                stderr_excerpt=self._excerpt(stderr),
                message=message,
            )
        )

    def _run_command_step(self, name: str, command: list[str], message: str | None = None) -> None:
        # Standard command wrapper to enforce dry-run behavior and uniform step logging.
        started_at = self._utc_now()
        if self.dry_run:
            self._record_step(
                name=name,
                status="simulated",
                started_at=started_at,
                command=command,
                message=message or "dry-run: command not executed",
            )
            return

        result = run_command(command, timeout=self.command_timeout, check=True)
        self._record_step(
            name=name,
            status="success",
            started_at=started_at,
            command=command,
            stdout=result.stdout,
            stderr=result.stderr,
            message=message,
        )

    def _check_required_tools(self) -> None:
        # Fast-fail before any destructive operation if dependencies are missing.
        started_at = self._utc_now()
        required_tools = ["cryptsetup", "scrub", "wipefs", "lsblk"]
        missing: list[str] = []

        for tool in required_tools:
            result = run_command(["which", tool], timeout=10, check=False)
            if result.returncode != 0:
                missing.append(tool)

        if missing:
            missing_list = ", ".join(missing)
            self._record_step(
                name="Preflight: required tools",
                status="failed",
                started_at=started_at,
                message=f"missing required tool(s): {missing_list}",
            )
            raise RuntimeError(f"missing required tool(s): {missing_list}")

        self._record_step(
            name="Preflight: required tools",
            status="success",
            started_at=started_at,
            message="all required tools are available",
        )

    def _check_device_exists(self) -> None:
        # Verify the target path exists and is a block device, not a regular file.
        started_at = self._utc_now()
        if not os.path.exists(self.device_path):
            self._record_step(
                name="Preflight: device exists",
                status="failed",
                started_at=started_at,
                message=f"device not found: {self.device_path}",
            )
            raise RuntimeError(f"device not found: {self.device_path}")

        mode = os.stat(self.device_path).st_mode
        if not stat.S_ISBLK(mode):
            self._record_step(
                name="Preflight: block device",
                status="failed",
                started_at=started_at,
                message=f"not a block device: {self.device_path}",
            )
            raise RuntimeError(f"not a block device: {self.device_path}")

        self._record_step(
            name="Preflight: device exists",
            status="success",
            started_at=started_at,
            message="target device exists and is a block device",
        )

    def _check_mount_state(self) -> None:
        # Mounted drives are rejected by default to prevent accidental data loss.
        started_at = self._utc_now()
        result = run_command(["lsblk", "-n", "-o", "MOUNTPOINT", self.device_path], timeout=30, check=False)
        mountpoints = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        if mountpoints and self.mount_mode == "deny":
            joined = ", ".join(mountpoints)
            self._record_step(
                name="Preflight: mount policy",
                status="failed",
                started_at=started_at,
                command=["lsblk", "-n", "-o", "MOUNTPOINT", self.device_path],
                stdout=result.stdout,
                stderr=result.stderr,
                message=f"device appears mounted: {joined}",
            )
            raise RuntimeError(f"refusing to wipe mounted device: {self.device_path}")

        status = "success" if not mountpoints else "warning"
        message = "device is not mounted" if not mountpoints else "device has mountpoints but policy allows it"
        self._record_step(
            name="Preflight: mount policy",
            status=status,
            started_at=started_at,
            command=["lsblk", "-n", "-o", "MOUNTPOINT", self.device_path],
            stdout=result.stdout,
            stderr=result.stderr,
            message=message,
        )

    def preflight_checks(self) -> None:
        """Run all safety checks before touching the target drive."""
        self._check_required_tools()
        self._check_device_exists()
        self._check_mount_state()

    def generate_temporary_key(self) -> None:
        """Create ephemeral key material used to set up the LUKS container."""
        started_at = self._utc_now()
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
        key_path = Path(self.temp_dir) / f"wipe-key-{secrets.token_hex(8)}.bin"

        if self.dry_run:
            self.key_file_path = str(key_path)
            self._record_step(
                name="Generate temporary key",
                status="simulated",
                started_at=started_at,
                message=f"dry-run: key would be generated at {self.key_file_path}",
            )
            return

        key_bytes = secrets.token_bytes(64)
        with key_path.open("wb") as key_file:
            key_file.write(key_bytes)
        # Restrict permissions to root/current user only.
        os.chmod(key_path, 0o600)

        self.key_file_path = str(key_path)
        self._record_step(
            name="Generate temporary key",
            status="success",
            started_at=started_at,
            message=f"temporary key generated at {self.key_file_path}",
        )

    def create_luks2_container(self) -> None:
        """Format the target as LUKS2 using the temporary key file."""
        if not self.key_file_path:
            raise RuntimeError("temporary key file is not available")
        self._run_command_step(
            name="Create LUKS2 encrypted container",
            command=[
                "cryptsetup",
                "luksFormat",
                "--type",
                "luks2",
                "--batch-mode",
                "--key-file",
                self.key_file_path,
                self.device_path,
            ],
        )

    def open_encrypted_mapping(self) -> None:
        """Open the LUKS container and expose it under /dev/mapper."""
        if not self.key_file_path:
            raise RuntimeError("temporary key file is not available")
        self._run_command_step(
            name="Open encrypted mapping",
            command=[
                "cryptsetup",
                "open",
                "--key-file",
                self.key_file_path,
                self.device_path,
                self.mapping_name,
            ],
        )

    def write_across_encrypted_volume(self) -> None:
        """Overwrite all logical blocks through the encrypted mapping using scrub."""
        mapped_device = f"/dev/mapper/{self.mapping_name}"

        command = ["scrub", "-f", mapped_device]
        if self.algorithm and self.algorithm not in {"scrub", "default"}:
            command = ["scrub", "-f", "-p", self.algorithm, mapped_device]

        self._run_command_step(
            name="Write across encrypted volume",
            command=command,
        )

    def close_encrypted_mapping(self) -> None:
        """Close the mapper device before metadata destruction steps."""
        self._run_command_step(
            name="Close encrypted mapping",
            command=["cryptsetup", "close", self.mapping_name],
        )

    def destroy_luks_header(self) -> None:
        """Erase LUKS metadata so prior encrypted content is not re-openable."""
        self._run_command_step(
            name="Destroy LUKS header",
            command=["cryptsetup", "erase", self.device_path],
        )

    def remove_residual_signatures(self) -> None:
        """Remove leftover filesystem signatures to reduce recovery hints."""
        self._run_command_step(
            name="Remove filesystem signatures",
            command=["wipefs", "--all", "--force", self.device_path],
        )

    def final_hdd_zero_pass(self) -> None:
        """For HDD only: add a final clear pass with zeros on the raw device."""
        if self.media_type.upper() != "HDD":
            started_at = self._utc_now()
            self._record_step(
                name="Final HDD zero pass",
                status="skipped",
                started_at=started_at,
                message="media is not HDD; final zero pass skipped",
            )
            return

        self._run_command_step(
            name="Final HDD zero pass",
            command=["scrub", "-f", "-p", "fillzero", self.device_path],
        )

    def _cleanup_key_file(self) -> None:
        # Best-effort cleanup: never raise from here to avoid masking prior failures.
        if not self.key_file_path:
            return

        started_at = self._utc_now()
        try:
            if self.dry_run:
                self._record_step(
                    name="Cleanup temporary key",
                    status="simulated",
                    started_at=started_at,
                    message=f"dry-run: key would be removed at {self.key_file_path}",
                )
            else:
                if os.path.exists(self.key_file_path):
                    os.remove(self.key_file_path)
                self._record_step(
                    name="Cleanup temporary key",
                    status="success",
                    started_at=started_at,
                    message="temporary key removed",
                )
        finally:
            self.key_file_path = None

    def execute(self) -> dict[str, Any]:
        """Execute the wipe workflow end-to-end and return structured step results."""
        try:
            # Order matters: each step depends on successful completion of the prior step.
            self.preflight_checks()
            self.generate_temporary_key()
            self.create_luks2_container()
            self.open_encrypted_mapping()
            self.write_across_encrypted_volume()
            self.close_encrypted_mapping()
            self.destroy_luks_header()
            self.remove_residual_signatures()
            self.final_hdd_zero_pass()
            result = WipeResult(
                device_path=self.device_path,
                status="success",
                steps=self.steps,
                failure_reason=None,
            )
            return result.to_dict()

        except (RuntimeError, CommandRunnerError, CommandRunnerTimeout, OSError) as exc:
            # Record failure as a final step so callers get a complete timeline.
            started_at = self._utc_now()
            self._record_step(
                name="Wipe process",
                status="failed",
                started_at=started_at,
                message=str(exc),
            )
            result = WipeResult(
                device_path=self.device_path,
                status="failed",
                steps=self.steps,
                failure_reason=str(exc),
            )
            return result.to_dict()
        finally:
            # Always attempt to remove temporary key material.
            self._cleanup_key_file()