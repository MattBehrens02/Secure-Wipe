import subprocess
import sys
import tomllib

from pathlib import Path

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header
from modules import smartctl


def main() -> int:
	try:
		app_config = config.load_config()
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		print(f"Configuration error: {exc}", file=sys.stderr)
		return 1

	if app_config.drive_detection.collect_smart_info and not smartctl.is_smartctl_available():
		print(
			"Warning: SMART collection is enabled but 'smartctl' is not installed; SMART data will be unavailable.",
			file=sys.stderr,
		)

	if not app_config.runtime.environment == "dev": 
		subprocess.run(["tput", "smcup"], check=False) # Switch to alternate screen buffer
		subprocess.run("clear")

	header.print_header()

	# Ensure required runtime directories exist.
	for dir_attr in ("logs_dir", "reports_dir", "state_dir", "temp_dir"):
		dir_path = Path(getattr(app_config.paths, dir_attr))
		if not dir_path.exists():
			try:
				dir_path.mkdir(parents=True, exist_ok=True)
				print(f"Created missing directory: {dir_path}")
			except PermissionError:
				print(f"Warning: cannot create directory {dir_path} (permission denied) — skipping.", file=sys.stderr)

	try: 
		print(
			"Loaded configuration: "
			f"environment={app_config.runtime.environment}, "
			f"dry_run={app_config.runtime.dry_run}"
		)

		selected_drives = drive_detection.run(app_config)
		if selected_drives == []:
			print("No drives detected.")
			return 1

		if app_config.reporting.reports_enabled:
			report_path = reporting.generate_detection_json_report(app_config, selected_drives)
			print(f"Detection report written to: {report_path}")

		if not app_config.runtime.dry_run:
			print("\n[STUB] Starting drive wiping process...")

		# wipe_drives(selected_drive, app_config.wipe)
	
	finally:
		if not app_config.runtime.environment == "dev":
			subprocess.run(["tput", "rmcup"], check=False) # Restore original screen buffer

	return 0


if __name__ == "__main__":
	raise SystemExit(main())