import json
import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.version import AppVersion

VERSION = AppVersion()

DEFAULT_LOCK_STALE_SECONDS = 7200
DEFAULT_RESUME_MAX_AGE_SECONDS = 86400


class RecoveryLockError(Exception):
    """Raised when lock acquisition cannot proceed safely."""


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_iso(value: str) -> datetime | None:
    """Parse ISO timestamp safely, returning None when invalid."""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _sanitize_token(value: str) -> str:
    """Create a stable filename-safe token from an identifier."""
    token = value.strip().replace("/", "_").replace(" ", "_")
    return token.strip("_") or "unknown_drive"


def recovery_key(drive_path: str, drive_serial: str | None = None) -> str:
    """Return stable key for recovery state identity.

    Serial number is preferred because device paths can change across boots.
    """
    serial = (drive_serial or "").strip()
    if serial:
        return f"serial_{_sanitize_token(serial)}"
    return f"path_{_sanitize_token(drive_path)}"


def state_file_path(
    state_dir: str | Path,
    drive_path: str,
    drive_serial: str | None = None,
) -> Path:
    """Resolve checkpoint state file path for a given drive identity."""
    base = Path(state_dir)
    filename = f"{recovery_key(drive_path, drive_serial=drive_serial)}.state.json"
    return base / filename


@dataclass
class RecoveryState:
    """Persisted recovery checkpoint for a single drive wipe session.

    This model is intentionally self-contained and serialization-friendly so it
    can be written directly to JSON and restored after interruption.
    """

    # Version metadata
    app_name: str = VERSION.app_name
    app_version: str = VERSION.app_version
    schema_version: str = VERSION.recovery_schema_version

    # Session identity
    session_id: str = ""
    drive_path: str = ""

    # Runtime artifact context
    mapping_name: str = ""
    keyfile_path: str = ""

    # Progress state
    status: str = "in_progress"  # in_progress | interrupted | failed | completed
    current_step: str = ""
    step_history: list[str] = field(default_factory=list)

    # Resume controls
    resume_attempts: int = 0
    max_resume_attempts: int = 3

    # Diagnostics
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timing
    started_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def touch(self) -> None:
        """Refresh the `updated_at` timestamp."""
        self.updated_at = _utc_now_iso()

    def mark_step_started(self, step_name: str) -> None:
        """Record that a step has started."""
        self.current_step = step_name
        self.status = "in_progress"
        self.step_history.append(f"start:{step_name}")
        self.touch()

    def mark_step_completed(self, step_name: str) -> None:
        """Record that a step has completed."""
        self.current_step = step_name
        self.step_history.append(f"done:{step_name}")
        self.touch()

    def mark_interrupted(self, error_message: str | None = None) -> None:
        """Mark this recovery session as interrupted."""
        self.status = "interrupted"
        self.last_error = error_message
        self.touch()

    def mark_failed(self, error_message: str | None = None) -> None:
        """Mark this recovery session as failed."""
        self.status = "failed"
        self.last_error = error_message
        self.touch()

    def mark_completed(self) -> None:
        """Mark this recovery session as completed successfully."""
        self.status = "completed"
        self.last_error = None
        self.touch()

    def increment_resume_attempts(self) -> None:
        """Increment resume attempts counter for this state."""
        self.resume_attempts += 1
        self.touch()

    def can_resume(self) -> bool:
        """Return True when this session is eligible for resume."""
        return self.status in {"in_progress", "interrupted", "failed"} and (
            self.resume_attempts < self.max_resume_attempts
        )

    def is_terminal(self) -> bool:
        """Return True when the session reached a terminal state."""
        return self.status in {"completed", "failed"}

    def to_dict(self) -> dict[str, Any]:
        """Serialize recovery state to plain dictionary for JSON persistence."""
        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "drive_path": self.drive_path,
            "mapping_name": self.mapping_name,
            "keyfile_path": self.keyfile_path,
            "status": self.status,
            "current_step": self.current_step,
            "step_history": list(self.step_history),
            "resume_attempts": self.resume_attempts,
            "max_resume_attempts": self.max_resume_attempts,
            "last_error": self.last_error,
            "metadata": dict(self.metadata),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecoveryState":
        """Build RecoveryState from dictionary data.

        Unknown keys are ignored to preserve forward compatibility and missing
        keys fall back to dataclass defaults.
        """
        return cls(
            app_name=str(data.get("app_name", VERSION.app_name)),
            app_version=str(data.get("app_version", VERSION.app_version)),
            schema_version=str(data.get("schema_version", VERSION.recovery_schema_version)),
            session_id=str(data.get("session_id", "")),
            drive_path=str(data.get("drive_path", "")),
            mapping_name=str(data.get("mapping_name", "")),
            keyfile_path=str(data.get("keyfile_path", "")),
            status=str(data.get("status", "in_progress")),
            current_step=str(data.get("current_step", "")),
            step_history=list(data.get("step_history", [])),
            resume_attempts=int(data.get("resume_attempts", 0)),
            max_resume_attempts=int(data.get("max_resume_attempts", 3)),
            last_error=(str(data["last_error"]) if data.get("last_error") is not None else None),
            metadata=dict(data.get("metadata", {})),
            started_at=str(data.get("started_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )


def save_state(state_dir: str | Path, state: RecoveryState) -> Path:
    """Persist state atomically to disk and return resulting file path."""
    if not state.drive_path:
        raise ValueError("RecoveryState.drive_path is required to persist state")

    drive_serial = None
    if isinstance(state.metadata, dict):
        drive_serial = state.metadata.get("drive_serial")
    output_path = state_file_path(state_dir, state.drive_path, drive_serial=drive_serial)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    state.touch()
    payload = state.to_dict()
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())

    tmp_path.replace(output_path)
    return output_path


def load_state(
    state_dir: str | Path,
    drive_path: str,
    drive_serial: str | None = None,
) -> RecoveryState | None:
    """Load persisted state for a drive. Returns None when missing/corrupt."""
    candidate_paths: list[Path] = []
    if drive_serial:
        candidate_paths.append(state_file_path(state_dir, drive_path, drive_serial=drive_serial))
    candidate_paths.append(state_file_path(state_dir, drive_path))

    input_path = next((path for path in candidate_paths if path.exists()), None)
    if input_path is None:
        return None

    try:
        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    return RecoveryState.from_dict(data)


def clear_state(
    state_dir: str | Path,
    drive_path: str,
    drive_serial: str | None = None,
) -> bool:
    """Delete persisted state for a drive. Returns True when at least one file is deleted."""
    targets = [state_file_path(state_dir, drive_path)]
    if drive_serial:
        targets.append(state_file_path(state_dir, drive_path, drive_serial=drive_serial))

    deleted_any = False
    for target in targets:
        if target.exists():
            target.unlink(missing_ok=True)
            deleted_any = True

    return deleted_any


def list_incomplete_states(state_dir: str | Path) -> list[RecoveryState]:
    """Return all persisted non-completed recovery states from state_dir."""
    base = Path(state_dir)
    if not base.exists():
        return []

    incomplete: list[RecoveryState] = []
    for state_path in sorted(base.glob("*.state.json")):
        try:
            with state_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

        if not isinstance(raw, dict):
            continue

        state = RecoveryState.from_dict(raw)
        if state.status in {"in_progress", "interrupted", "failed"}:
            incomplete.append(state)

    return incomplete


def should_offer_resume(
    state: RecoveryState,
    max_age_seconds: int = DEFAULT_RESUME_MAX_AGE_SECONDS,
    allow_failed_resume: bool = False,
) -> bool:
    """Evaluate whether this state should be offered for resume."""
    if state.status == "completed":
        return False
    if state.status == "failed" and not allow_failed_resume:
        return False
    if not state.can_resume():
        return False

    updated_at = _parse_utc_iso(state.updated_at)
    if updated_at is None:
        return False

    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return age_seconds <= max_age_seconds


def _lock_payload() -> dict[str, Any]:
    """Build lock file payload with process metadata."""
    return {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": _utc_now_iso(),
        "app_name": VERSION.app_name,
        "app_version": VERSION.app_version,
    }


def acquire_lock(
    lock_file_path: str | Path,
    stale_after_seconds: int = DEFAULT_LOCK_STALE_SECONDS,
) -> tuple[bool, str | None]:
    """Acquire singleton process lock; optionally evict stale lock files."""
    lock_path = Path(lock_file_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        stale = _is_lock_stale(lock_path, stale_after_seconds)
        if stale:
            lock_path.unlink(missing_ok=True)
            return acquire_lock(lock_path, stale_after_seconds=stale_after_seconds)

        return False, f"Lock file exists at {lock_path}; another wipe session may be active"

    payload = _lock_payload()
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        json.dump(payload, lock_file, indent=2, sort_keys=True)
        lock_file.flush()
        os.fsync(lock_file.fileno())

    return True, None


def _is_lock_stale(lock_path: Path, stale_after_seconds: int) -> bool:
    """Return True if lock is older than stale threshold or unreadable."""
    try:
        with lock_path.open("r", encoding="utf-8") as lock_file:
            data = json.load(lock_file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return True

    if not isinstance(data, dict):
        return True

    created_at = _parse_utc_iso(str(data.get("created_at", "")))
    if created_at is None:
        return True

    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    return age_seconds > stale_after_seconds


def release_lock(lock_file_path: str | Path) -> None:
    """Release process lock file."""
    Path(lock_file_path).unlink(missing_ok=True)