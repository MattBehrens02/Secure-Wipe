import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _get_detail_level(app_config: Any) -> str:
	"""Return the configured report detail level, defaulting to verbose."""
	level = getattr(getattr(app_config, "reporting", object()), "detail_level", "verbose")
	return str(level).lower()


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
