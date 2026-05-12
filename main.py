import subprocess
import sys
import tomllib

from pathlib import Path

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header


def main() -> int:
	try:
		app_config = config.load_config()
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		print(f"Configuration error: {exc}", file=sys.stderr)
		return 1

	if not app_config.runtime.environment == "dev": 
		subprocess.run(["tput", "smcup"], check=False) # Switch to alternate screen buffer

	header.print_header()

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