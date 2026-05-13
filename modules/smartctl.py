import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


class SmartctlError(Exception):
    """Raised when smartctl cannot be executed or its output cannot be interpreted."""


@dataclass
class SmartctlResult:
    """Container for raw smartctl execution results."""

    device_path: str
    returncode: int
    stdout: str
    stderr: str


def is_smartctl_available() -> bool:
    """Return True when smartctl is available in PATH."""
    return shutil.which("smartctl") is not None


def _run_smartctl(device_path: str, timeout: int = 10) -> SmartctlResult:
    """Execute smartctl for a single device and capture its output."""
    try:
        completed = subprocess.run(
            ["smartctl", "--json", "--all", device_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmartctlError(f"smartctl timed out for {device_path}") from exc
    except OSError as exc:
        raise SmartctlError(f"failed to execute smartctl for {device_path}: {exc}") from exc

    return SmartctlResult(
        device_path=device_path,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=(completed.stderr or "").strip(),
    )


def collect_smart_info(device_path: str, timeout: int = 10) -> dict[str, Any] | None:
    """Collect SMART data for a device and return parsed JSON when available.

    The function is intentionally fail-open: if smartctl cannot collect data for a
    device, it returns None instead of raising, so drive detection and testing can
    continue even when hardware is unavailable.
    """
    result = _run_smartctl(device_path, timeout=timeout)

    if not result.stdout:
        return None

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SmartctlError(f"smartctl returned invalid JSON for {device_path}") from exc

    if not isinstance(parsed, dict):
        raise SmartctlError(f"smartctl returned unexpected JSON for {device_path}")

    if result.returncode != 0:
        parsed.setdefault("smartctl_returncode", result.returncode)
        if result.stderr:
            parsed.setdefault("smartctl_error", result.stderr)

    return parsed


def collect_smart_snapshot(device_paths: list[str], timeout: int = 10) -> dict[str, dict[str, Any] | None]:
    """Collect SMART data for multiple devices and return a path-to-data snapshot."""
    snapshot: dict[str, dict[str, Any] | None] = {}

    for device_path in device_paths:
        try:
            snapshot[device_path] = collect_smart_info(device_path, timeout=timeout)
        except SmartctlError:
            snapshot[device_path] = None

    return snapshot