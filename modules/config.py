
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import tomllib

@dataclass
class PathsConfig:
    project_root: str = "/app"
    logs_dir: str = "/app/logs"
    reports_dir: str = "/app/reports"
    state_dir: str = "/app/state"
    temp_dir: str = "/app/tmp"

@dataclass
class RuntimeConfig:
    environment: str = "dev"  # dev, test, prod
    dry_run: bool = True
    simulate_tools: bool = False
    require_root_user: bool = True

@dataclass
class SafetyConfig:
    require_explicit_device_selection: bool = True
    mount_handling_mode: str = "deny"  # deny | allow
    removable_drive_mode: str = "deny"     # deny | allow
    protected_device_patterns: List[str] = field(default_factory=lambda: ["/dev/sda", "/dev/nvme0n1"])
    confirmation_steps: int = 2 # 0 = none, 1 = single prompt: [y]es/[n]o, 2 = multi-step confirmation [y]es/[n]o + type "WIPE" to confirm (Recommended)

@dataclass
class DriveDetectionConfig:
    collect_smart_info: bool = True

@dataclass
class WipeConfig:
    method: str = "cryptographic"  # cryptographic, overwrite, hybrid
    overwrite_passes: int = 3
    block_size: str = "1M"
    command_timeout_seconds: int = 600
    per_device_timeout_minutes: int = 60

@dataclass
class VerificationConfig:
    enabled: bool = True
    strategy: str = "percentage"  # full, percentage, random_blocks
    sample_ratio: float = 0.05
    smart_checks_enabled: bool = True

@dataclass
class RecoveryConfig:
    checkpoint_interval_seconds: int = 60
    max_resume_attempts: int = 3
    lock_file_path: str = "/app/state/wipe.lock"
    lock_stale_seconds: int = 7200
    resume_state_max_age_seconds: int = 86400
    allow_failed_resume: bool = False

@dataclass
class ReportingConfig:
    reports_enabled: bool = True
    formats: List[str] = field(default_factory=lambda: ["json", "txt"])
    detail_level: str = "verbose"  # minimal | standard | verbose
    include_hardware_fingerprint: bool = True
    redact_sensitive_fields: bool = True
    operator_identifier: str = "unknown"
@dataclass
class UploadConfig:
    enabled: bool = False
    repo: Optional[str] = None
    branch: str = "main"
    path_template: str = "reports/{date}/{hostname}/"
    retry_count: int = 3

@dataclass
class LoggingConfig:
    enabled: bool = True
    level: str = "info"  # info | errors

@dataclass
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    drive_detection: DriveDetectionConfig = field(default_factory=DriveDetectionConfig)
    wipe: WipeConfig = field(default_factory=WipeConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    upload: UploadConfig = field(default_factory=UploadConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configuration.toml"

_ALLOWED_TOML_KEYS: dict[str, set[str]] = {
    "runtime": {"environment", "dry_run"},
    "safety": {"removable_drive_mode", "mount_handling_mode", "confirmation_steps"},
    "drive_detection": {"collect_smart_info"},
    "recovery": {
        "checkpoint_interval_seconds",
        "max_resume_attempts",
        "lock_file_path",
        "lock_stale_seconds",
        "resume_state_max_age_seconds",
        "allow_failed_resume",
    },
    "reporting": {"formats", "detail_level"},
    "logging": {"enabled", "level"},
}


def _apply_runtime_overrides(config: AppConfig, runtime_data: dict[str, Any]) -> None:
    if "environment" in runtime_data:
        config.runtime.environment = str(runtime_data["environment"])
    if "dry_run" in runtime_data:
        config.runtime.dry_run = bool(runtime_data["dry_run"])


def _apply_safety_overrides(config: AppConfig, safety_data: dict[str, Any]) -> None:
    if "removable_drive_mode" in safety_data:
        config.safety.removable_drive_mode = str(safety_data["removable_drive_mode"]).lower()
    if "mount_handling_mode" in safety_data:
        config.safety.mount_handling_mode = str(safety_data["mount_handling_mode"]).lower()
    if "confirmation_steps" in safety_data:
        config.safety.confirmation_steps = int(safety_data["confirmation_steps"])


def _apply_drive_detection_overrides(config: AppConfig, drive_detection_data: dict[str, Any]) -> None:
    if "collect_smart_info" in drive_detection_data:
        config.drive_detection.collect_smart_info = bool(drive_detection_data["collect_smart_info"])


def _apply_recovery_overrides(config: AppConfig, recovery_data: dict[str, Any]) -> None:
    if "checkpoint_interval_seconds" in recovery_data:
        config.recovery.checkpoint_interval_seconds = int(recovery_data["checkpoint_interval_seconds"])
    if "max_resume_attempts" in recovery_data:
        config.recovery.max_resume_attempts = int(recovery_data["max_resume_attempts"])
    if "lock_file_path" in recovery_data:
        config.recovery.lock_file_path = str(recovery_data["lock_file_path"])
    if "lock_stale_seconds" in recovery_data:
        config.recovery.lock_stale_seconds = int(recovery_data["lock_stale_seconds"])
    if "resume_state_max_age_seconds" in recovery_data:
        config.recovery.resume_state_max_age_seconds = int(recovery_data["resume_state_max_age_seconds"])
    if "allow_failed_resume" in recovery_data:
        config.recovery.allow_failed_resume = bool(recovery_data["allow_failed_resume"])


def _reject_unknown_toml_keys(raw_data: dict[str, Any]) -> None:
    unknown_tables = set(raw_data.keys()) - set(_ALLOWED_TOML_KEYS.keys())
    if unknown_tables:
        unknown_list = ", ".join(sorted(unknown_tables))
        raise ValueError(f"Unknown top-level configuration table(s): {unknown_list}")

    for table_name, allowed_keys in _ALLOWED_TOML_KEYS.items():
        table_value = raw_data.get(table_name)
        if table_value is None:
            continue
        if not isinstance(table_value, dict):
            raise ValueError(f"configuration table '{table_name}' must be a TOML table")

        unknown_keys = set(table_value.keys()) - allowed_keys
        if unknown_keys:
            unknown_list = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unknown key(s) under '{table_name}': {unknown_list}")


def _apply_reporting_overrides(config: AppConfig, reporting_data: dict[str, Any]) -> None:
    if "formats" in reporting_data:
        config.reporting.formats = list(reporting_data["formats"])
    if "detail_level" in reporting_data:
        config.reporting.detail_level = str(reporting_data["detail_level"]).lower()
        

def _apply_logging_overrides(config: AppConfig, logging_data: dict[str, Any]) -> None:
    if "enabled" in logging_data:
        config.logging.enabled = bool(logging_data["enabled"])
    if "level" in logging_data:
        config.logging.level = str(logging_data["level"]).lower()


def _validate_config(config: AppConfig) -> None:
    if config.runtime.environment not in {"dev", "test", "prod"}:
        raise ValueError("runtime.environment must be one of: dev, test, prod")

    valid_modes = {"deny", "allow"}
    if config.safety.removable_drive_mode not in valid_modes:
        raise ValueError("safety.removable_drive_mode must be one of: deny, allow")
    if config.safety.mount_handling_mode not in valid_modes:
        raise ValueError("safety.mount_handling_mode must be one of: deny, allow")

    if config.safety.confirmation_steps not in {0, 1, 2}:
        raise ValueError("safety.confirmation_steps must be 0, 1, or 2")

    if not isinstance(config.drive_detection.collect_smart_info, bool):
        raise ValueError("drive_detection.collect_smart_info must be a boolean")

    if config.recovery.checkpoint_interval_seconds <= 0:
        raise ValueError("recovery.checkpoint_interval_seconds must be > 0")

    if config.recovery.max_resume_attempts < 0:
        raise ValueError("recovery.max_resume_attempts must be >= 0")

    if config.recovery.lock_stale_seconds <= 0:
        raise ValueError("recovery.lock_stale_seconds must be > 0")

    if config.recovery.resume_state_max_age_seconds <= 0:
        raise ValueError("recovery.resume_state_max_age_seconds must be > 0")

    if not isinstance(config.recovery.allow_failed_resume, bool):
        raise ValueError("recovery.allow_failed_resume must be a boolean")

    if not isinstance(config.logging.enabled, bool):
        raise ValueError("logging.enabled must be a boolean")

    valid_levels = {"info", "errors"}
    if config.logging.level not in valid_levels:
        raise ValueError("logging.level must be one of: info, errors")

    valid_formats = {"json", "txt"}
    if not config.reporting.formats:
        raise ValueError("reporting.formats cannot be empty")
    for report_format in config.reporting.formats:
        if str(report_format) not in valid_formats:
            raise ValueError("reporting.formats can only contain: json, txt")

    valid_detail_levels = {"minimal", "standard", "verbose"}
    if config.reporting.detail_level not in valid_detail_levels:
        raise ValueError("reporting.detail_level must be one of: minimal, standard, verbose")


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """
    Load application config with safe defaults, optionally overridden by configuration.toml.

    Only a curated, user-facing subset is loaded from TOML so internal safety settings
    remain controlled in code unless explicitly exposed later.
    """
    config = AppConfig()
    target_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    if target_path.exists():
        with target_path.open("rb") as config_file:
            raw_data = tomllib.load(config_file)

        if not isinstance(raw_data, dict):
            raise ValueError("configuration.toml must contain top-level tables")

        _reject_unknown_toml_keys(raw_data)

        runtime_data = raw_data.get("runtime", {})
        _apply_runtime_overrides(config, runtime_data)

        safety_data = raw_data.get("safety", {})
        _apply_safety_overrides(config, safety_data)

        drive_detection_data = raw_data.get("drive_detection", {})
        _apply_drive_detection_overrides(config, drive_detection_data)

        recovery_data = raw_data.get("recovery", {})
        _apply_recovery_overrides(config, recovery_data)

        reporting_data = raw_data.get("reporting", {})
        _apply_reporting_overrides(config, reporting_data)

        logging_data = raw_data.get("logging", {})
        _apply_logging_overrides(config, logging_data)

    _validate_config(config)
    if config.runtime.environment == "prod":
        _project_root = Path(__file__).resolve().parent.parent
        config.paths.project_root = str(_project_root)
        config.paths.logs_dir    = str(_project_root / "logs")
        config.paths.reports_dir = str(_project_root / "reports")
        config.paths.state_dir   = str(_project_root / "state")
        config.paths.temp_dir    = str(_project_root / "tmp")
        if config.recovery.lock_file_path == "/app/state/wipe.lock":
            config.recovery.lock_file_path = str(_project_root / "state" / "wipe.lock")


    return config