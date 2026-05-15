import json
import platform
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class WipeReport:
	"""Comprehensive wipe operation report structure."""
	report_version: str = "1.0"
	timestamp_utc: str = ""
	operator_identifier: str = "unknown"
	hostname: str = ""
	platform: str = ""
	environment: str = ""
	drive_path: str = ""
	drive_name: str = ""
	drive_model: str = ""
	drive_vendor: str = ""
	drive_serial: str = ""
	drive_size: str = ""
	drive_size_human: str = ""
	drive_media_type: str = ""
	drive_transport: str = ""
	drive_removable: bool = False
	encryption: str = "LUKS2"
	key_size_bits: int = 256
	scrub_pattern: str = "nnsa"
	hdd_final_pass: bool = False
	status: str = "unknown"
	started_at: Optional[str] = None
	finished_at: Optional[str] = None
	duration_seconds: float = 0.0
	failed_step: Optional[str] = None
	error_message: Optional[str] = None
	step_durations: dict[str, float] = field(default_factory=dict)
	verification_status: str = "not_run"
	verification_checks_passed: list[str] = field(default_factory=list)
	verification_checks_failed: list[str] = field(default_factory=list)
	verification_errors: list[str] = field(default_factory=list)


def _serialize_drive_minimal(drive: Any) -> dict[str, Any]:
	"""Serialize only the bare minimum drive fields."""
	return {
		"path": getattr(drive, "path", ""),
		"size": getattr(drive, "size", ""),
	}


def _serialize_drive_standard(drive: Any) -> dict[str, Any]:
	"""Serialize standard drive metadata fields."""
	return {
		"path": getattr(drive, "path", ""),
		"size": getattr(drive, "size", ""),
		"media_type": getattr(drive, "media_type", "Unknown"),
		"model": getattr(drive, "model", ""),
		"vendor": getattr(drive, "vendor", ""),
		"serial": getattr(drive, "serial", ""),
		"transport": getattr(drive, "transport", ""),
		"removable": bool(getattr(drive, "removable", False)),
	}


def _serialize_drive_verbose(drive: Any) -> dict[str, Any]:
	"""Serialize complete drive metadata including SMART enrichment."""
	return {
		"name": getattr(drive, "name", ""),
		"path": getattr(drive, "path", ""),
		"size": getattr(drive, "size", ""),
		"media_type": getattr(drive, "media_type", "Unknown"),
		"model": getattr(drive, "model", ""),
		"vendor": getattr(drive, "vendor", ""),
		"serial": getattr(drive, "serial", ""),
		"type": getattr(drive, "type", ""),
		"mountpoints": list(getattr(drive, "mountpoints", []) or []),
		"removable": bool(getattr(drive, "removable", False)),
		"transport": getattr(drive, "transport", ""),
		"smart_data": getattr(drive, "smart_data", None),
	}


def _serialize_drive(drive: Any, detail_level: str) -> dict[str, Any]:
	"""Serialize a drive according to the configured reporting detail level."""
	if detail_level == "minimal":
		return _serialize_drive_minimal(drive)
	if detail_level == "standard":
		return _serialize_drive_standard(drive)
	return _serialize_drive_verbose(drive)


def _get_detail_level(app_config: Any) -> str:
	"""Return the configured report detail level, defaulting to verbose."""
	level = getattr(getattr(app_config, "reporting", object()), "detail_level", "verbose")
	return str(level).lower()


def _normalize_detail_level(detail_level: str) -> str:
	"""Normalize report detail level, defaulting to verbose."""
	level = str(detail_level).lower()
	if level in {"minimal", "standard", "verbose"}:
		return level
	return "verbose"


def _get_system_info() -> tuple[str, str]:
	"""Collect hostname and platform information."""
	try:
		hostname = socket.gethostname()
	except Exception:
		hostname = "unknown"
	
	try:
		plat = platform.platform()
	except Exception:
		plat = "unknown"
	
	return hostname, plat


def _humanize_size(size_bytes: str) -> str:
	"""Convert size in bytes to human-readable format."""
	try:
		size_int = int(size_bytes)
	except (ValueError, TypeError):
		return str(size_bytes)
	
	units = ["B", "KB", "MB", "GB", "TB"]
	size_float = float(size_int)
	
	for unit in units:
		if size_float < 1024.0:
			return f"{size_float:.1f} {unit}"
		size_float /= 1024.0
	
	return f"{size_float:.1f} PB"


def _format_duration(seconds: float) -> str:
	"""Convert seconds to human-readable duration string."""
	if seconds < 60:
		return f"{seconds:.2f}s"
	
	minutes = int(seconds // 60)
	secs = seconds % 60
	
	if minutes < 60:
		return f"{minutes}m {secs:.2f}s"
	
	hours = int(minutes // 60)
	minutes = minutes % 60
	return f"{hours}h {minutes}m {secs:.2f}s"


def generate_wipe_report(
	drive: Any,
	wipe_result: Any,
	app_config: Any,
	verification_result: Optional[Any] = None,
) -> WipeReport:
	"""Generate comprehensive wipe report from results and configuration."""
	hostname, plat = _get_system_info()
	
	# Get environment and operator from config
	environment = getattr(getattr(app_config, "runtime", object()), "environment", "unknown")
	operator = getattr(getattr(app_config, "reporting", object()), "operator_identifier", "unknown")
	
	# Extract drive metadata
	drive_size_str = getattr(drive, "size", "")
	drive_size_human = _humanize_size(drive_size_str)
	
	# Determine if HDD based on media_type
	media_type = getattr(drive, "media_type", "Unknown")
	is_hdd = media_type.upper() == "HDD"
	
	# Extract wipe result metadata
	status = getattr(wipe_result, "status", "unknown")
	started_at = getattr(wipe_result, "started_at", None)
	finished_at = getattr(wipe_result, "finished_at", None)
	duration = getattr(wipe_result, "duration_seconds", 0.0)
	failed_step = getattr(wipe_result, "failed_step", None)
	error_msg = getattr(wipe_result, "error_message", None)
	step_durations = getattr(wipe_result, "step_durations_seconds", {})
	
	# Verification placeholder
	verification_status = "pending" if status == "success" else "not_run"
	verification_passed = []
	verification_failed = []
	verification_errors = []
	
	if verification_result:
		verification_status = getattr(verification_result, "status", "pending")
		verification_passed = getattr(verification_result, "checks_passed", [])
		verification_failed = getattr(verification_result, "checks_failed", [])
		verification_errors = getattr(verification_result, "verification_errors", [])
	
	report = WipeReport(
		timestamp_utc=datetime.now(timezone.utc).isoformat(),
		operator_identifier=operator,
		hostname=hostname,
		platform=plat,
		environment=environment,
		drive_path=getattr(drive, "path", ""),
		drive_name=getattr(drive, "name", ""),
		drive_model=getattr(drive, "model", ""),
		drive_vendor=getattr(drive, "vendor", ""),
		drive_serial=getattr(drive, "serial", ""),
		drive_size=drive_size_str,
		drive_size_human=drive_size_human,
		drive_media_type=media_type,
		drive_transport=getattr(drive, "transport", ""),
		drive_removable=bool(getattr(drive, "removable", False)),
		encryption="LUKS2",
		key_size_bits=256,
		scrub_pattern="nnsa",
		hdd_final_pass=is_hdd,
		status=status,
		started_at=started_at,
		finished_at=finished_at,
		duration_seconds=duration,
		failed_step=failed_step,
		error_message=error_msg,
		step_durations=step_durations,
		verification_status=verification_status,
		verification_checks_passed=verification_passed,
		verification_checks_failed=verification_failed,
		verification_errors=verification_errors,
	)
	
	return report


def _serialize_wipe_report(report: WipeReport, detail_level: str = "verbose") -> dict[str, Any]:
	"""Serialize a wipe report according to the configured detail level."""
	level = _normalize_detail_level(detail_level)

	base_report = {
		"report_version": report.report_version,
		"report_detail_level": level,
		"timestamp_utc": report.timestamp_utc,
		"operator_identifier": report.operator_identifier,
		"machine": {
			"hostname": report.hostname,
			"environment": report.environment,
		},
		"drive": {
			"path": report.drive_path,
			"size_human": report.drive_size_human,
			"media_type": report.drive_media_type,
		},
		"wipe_status": {
			"status": report.status,
			"started_at": report.started_at,
			"finished_at": report.finished_at,
			"duration_seconds": report.duration_seconds,
		},
		"verification": {
			"status": report.verification_status,
		},
	}

	if level in {"standard", "verbose"}:
		base_report["machine"]["platform"] = report.platform
		base_report["drive"].update(
			{
				"name": report.drive_name,
				"model": report.drive_model,
				"vendor": report.drive_vendor,
				"serial": report.drive_serial,
				"transport": report.drive_transport,
				"removable": report.drive_removable,
			}
		)
		base_report["wipe_method"] = {
			"encryption": report.encryption,
			"key_size_bits": report.key_size_bits,
			"scrub_pattern": report.scrub_pattern,
			"hdd_final_pass": report.hdd_final_pass,
		}
		base_report["wipe_status"].update(
			{
				"failed_step": report.failed_step,
				"error_message": report.error_message,
			}
		)
		base_report["verification"].update(
			{
				"checks_passed_count": len(report.verification_checks_passed),
				"checks_failed_count": len(report.verification_checks_failed),
			}
		)

	if level == "verbose":
		base_report["drive"]["size"] = report.drive_size
		base_report["wipe_status"]["step_durations"] = report.step_durations
		base_report["verification"].update(
			{
				"checks_passed": report.verification_checks_passed,
				"checks_failed": report.verification_checks_failed,
				"verification_errors": report.verification_errors,
			}
		)

	return base_report


def wipe_report_to_json(report: WipeReport, pretty: bool = True, detail_level: str = "verbose") -> str:
	"""Serialize WipeReport to JSON string."""
	report_dict = _serialize_wipe_report(report, detail_level)

	if pretty:
		return json.dumps(report_dict, indent=2)
	return json.dumps(report_dict)


def wipe_report_to_text(report: WipeReport, detail_level: str = "verbose") -> str:
	"""Serialize WipeReport to human-readable text format."""
	level = _normalize_detail_level(detail_level)
	lines = []
	
	# Header
	lines.append("=" * 80)
	lines.append(" " * 20 + "SECUREWIPE OPERATION REPORT")
	lines.append("=" * 80)
	lines.append("")
	
	# Timestamp
	lines.append("TIMESTAMP")
	lines.append(f"  UTC:        {report.timestamp_utc}")
	lines.append(f"  Operator:   {report.operator_identifier}")
	lines.append("")
	
	# Machine information
	lines.append("MACHINE INFORMATION")
	lines.append(f"  Hostname:   {report.hostname}")
	if level in {"standard", "verbose"}:
		lines.append(f"  Platform:   {report.platform}")
	lines.append(f"  Environment: {report.environment}")
	lines.append("")
	
	# Drive metadata
	lines.append("DRIVE METADATA")
	lines.append(f"  Path:       {report.drive_path}")
	lines.append(f"  Capacity:   {report.drive_size_human}")
	lines.append(f"  Type:       {report.drive_media_type}")
	if level in {"standard", "verbose"}:
		lines.append(f"  Device:     {report.drive_name}")
		lines.append(f"  Model:      {report.drive_model}")
		lines.append(f"  Vendor:     {report.drive_vendor}")
		lines.append(f"  Serial:     {report.drive_serial}")
		lines.append(f"  Transport:  {report.drive_transport}")
		lines.append(f"  Removable:  {'Yes' if report.drive_removable else 'No'}")
	lines.append("")
	
	# Wipe method
	if level in {"standard", "verbose"}:
		lines.append("WIPE METHOD")
		lines.append(f"  Encryption:     {report.encryption} ({report.key_size_bits}-bit AES)")
		lines.append(f"  Overwrite:      {report.scrub_pattern.upper()} multi-pass")
		lines.append(f"  HDD Final Pass: {'Yes (HDD detected)' if report.hdd_final_pass else 'No (SSD detected)'}")
		lines.append("")
	
	# Wipe results
	lines.append("WIPE RESULTS")
	status_icon = "✓" if report.status == "success" else "✗"
	status_text = report.status.upper()
	lines.append(f"  Status:     {status_icon} {status_text}")
	
	if report.started_at:
		lines.append(f"  Started:    {report.started_at}")
	if report.finished_at:
		lines.append(f"  Finished:   {report.finished_at}")
	
	if report.duration_seconds:
		lines.append(f"  Duration:   {_format_duration(report.duration_seconds)}")
	lines.append("")
	
	# Step timeline
	if level == "verbose" and report.step_durations:
		lines.append("STEP TIMELINE")
		
		# Find longest step for callout
		longest_step = max(report.step_durations.items(), key=lambda x: x[1]) if report.step_durations else None
		
		for step_name, duration in report.step_durations.items():
			human_name = " ".join(word.capitalize() for word in step_name.split("_"))
			callout = " (critical path)" if longest_step and step_name == longest_step[0] else ""
			lines.append(f"  {human_name}:{' ' * (40 - len(human_name))} {duration}s{callout}")
		
		lines.append("")
	
	# Failure details
	if report.status == "failed" and level in {"standard", "verbose"}:
		lines.append("FAILURE DETAILS")
		if report.failed_step:
			human_step = " ".join(word.capitalize() for word in report.failed_step.split("_"))
			lines.append(f"  Failed Step:    {human_step}")
		
		if report.error_message:
			lines.append(f"  Error Message:  {report.error_message}")
		
		lines.append("")
		lines.append("RECOVERY INFORMATION")
		lines.append("  Container Status:       Attempting cleanup (see logs)")
		lines.append("  Temporary Key:          Attempting deletion")
		lines.append("  Encrypted Mapping:      Attempted mapper close")
		lines.append("")
	
	# Verification status
	lines.append("VERIFICATION STATUS")
	lines.append(f"  Status:     {report.verification_status.capitalize()}")
	
	if level in {"standard", "verbose"} and report.verification_checks_passed:
		lines.append(f"  Passed:     {len(report.verification_checks_passed)} checks")
	if level in {"standard", "verbose"} and report.verification_checks_failed:
		lines.append(f"  Failed:     {len(report.verification_checks_failed)} checks")
	
	if report.status == "failed":
		lines.append("  Reason:     Wipe operation failed before verification could execute")
	elif report.verification_status == "pending":
		lines.append("  Note:       Verification module not yet executed")
	
	lines.append("")
	
	# Recommended actions for failed wipe
	if report.status == "failed" and level == "verbose":
		lines.append("RECOMMENDED ACTIONS")
		lines.append("  1. Check system resources (memory, disk space)")
		lines.append("  2. Review logs in logs/YYYY-MM-DD.log for detailed error context")
		lines.append("  3. Check if container /dev/mapper/wipe_* still exists")
		lines.append("  4. Use recovery module to resume operation")
		lines.append("  5. Contact system administrator if issue persists")
		lines.append("")
	
	# Footer
	lines.append("=" * 80)
	
	return "\n".join(lines)


def save_wipe_report(
	report: WipeReport,
	reports_dir: str | Path = "./reports",
	detail_level: str = "verbose",
) -> tuple[Path, Path]:
	"""Save wipe report as JSON and text files.
	
	Returns:
		Tuple of (json_path, text_path)
	"""
	reports_path = Path(reports_dir)
	reports_path.mkdir(parents=True, exist_ok=True)
	
	# Generate filename: YYYYMMDDTHHMM-device-serial.{json,txt}
	timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
	device_name = Path(report.drive_path).name if report.drive_path else "unknown"
	serial = report.drive_serial if report.drive_serial else "unknown"
	safe_serial = "".join(c if c.isalnum() else "_" for c in serial)
	
	base_filename = f"{timestamp_str}-{device_name}-{safe_serial}"
	
	# Write JSON
	json_path = reports_path / f"{base_filename}.json"
	json_path.write_text(wipe_report_to_json(report, pretty=True, detail_level=detail_level))
	
	# Write text
	text_path = reports_path / f"{base_filename}.txt"
	text_path.write_text(wipe_report_to_text(report, detail_level=detail_level))
	
	return json_path, text_path


def build_detection_report(app_config: Any, selected_drives: list[Any]) -> dict[str, Any]:
	"""Build a drive-selection report payload based on configured detail level."""
	timestamp = datetime.now(timezone.utc)
	detail_level = _get_detail_level(app_config)
	drive_entries = [_serialize_drive(drive, detail_level) for drive in selected_drives]
	
	return {
		"timestamp_utc": timestamp.isoformat(),
		"report_detail_level": detail_level,
		"run": {
			"environment": app_config.runtime.environment,
			"dry_run": app_config.runtime.dry_run,
		},
		"selection": {
			"selected_count": len(selected_drives),
			"selected_paths": [entry["path"] for entry in drive_entries],
		},
		"drives": drive_entries,
	}


def write_json_report(report_data: dict[str, Any], reports_dir: str) -> Path:
	"""Persist a report dictionary as JSON and return the output path."""
	output_dir = Path(reports_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	filename = f"detection_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
	output_path = output_dir / filename

	with output_path.open("w", encoding="utf-8") as report_file:
		json.dump(report_data, report_file, indent=2, sort_keys=True)

	return output_path


def generate_detection_json_report(app_config: Any, selected_drives: list[Any]) -> Path:
	"""Build and write a basic JSON report for selected drives."""
	report_data = build_detection_report(app_config, selected_drives)
	return write_json_report(report_data, app_config.paths.reports_dir)
