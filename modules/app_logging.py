from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER_NAME = "securewipe"
_LOGGER_CONFIGURED = False
_LOGGING_ENABLED = False


def _normalize_level(level: str) -> str:
    value = (level or "info").strip().lower()
    if value not in {"info", "errors"}:
        return "info"
    return value


def setup_logging(app_config: Any) -> None:
    """Configure daily append-only file logging.

    Log file names are UTC-day based, for example: 2026-05-15.log.
    """
    global _LOGGER_CONFIGURED
    global _LOGGING_ENABLED

    logging_cfg = getattr(app_config, "logging", object())
    enabled = bool(getattr(logging_cfg, "enabled", True))
    level_name = _normalize_level(str(getattr(logging_cfg, "level", "info")))

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()

    if not enabled:
        _LOGGING_ENABLED = False
        _LOGGER_CONFIGURED = True
        return

    paths_cfg = getattr(app_config, "paths", object())
    logs_dir = Path(getattr(paths_cfg, "logs_dir", "./logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)

    day_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logfile_path = logs_dir / f"{day_stamp}.log"

    handler = logging.FileHandler(logfile_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO if level_name == "info" else logging.ERROR)

    _LOGGING_ENABLED = True
    _LOGGER_CONFIGURED = True


def _get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_info(message: str) -> None:
    if not _LOGGER_CONFIGURED or not _LOGGING_ENABLED:
        return
    _get_logger().info(message)


def log_error(message: str) -> None:
    if not _LOGGER_CONFIGURED or not _LOGGING_ENABLED:
        return
    _get_logger().error(message)
