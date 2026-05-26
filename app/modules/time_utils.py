from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


def _runtime_timezone_name(app_config: Any) -> str:
    runtime_cfg = getattr(app_config, "runtime", object())
    value = getattr(runtime_cfg, "timezone", "UTC")
    return str(value or "UTC").strip()


def resolve_output_timezone(app_config: Any) -> tzinfo:
    """Resolve timezone used for app-generated output names.

    Supports:
    - "UTC" (default)
    - "local" or "system" for host local timezone
    - IANA timezone names (for example, "America/Chicago")
    """
    tz_name = _runtime_timezone_name(app_config)

    if tz_name.lower() in {"local", "system"}:
        local_tz = datetime.now().astimezone().tzinfo
        return local_tz or timezone.utc

    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass

    return timezone.utc


def now_for_output_names(app_config: Any) -> datetime:
    """Return current datetime in configured runtime timezone."""
    return datetime.now(resolve_output_timezone(app_config))
