import sys
import tomllib

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header, dir_check
from modules import smartctl
from modules.terminal import TerminalUI


def main() -> int:
	try:
		app_config = config.load_config()
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		print(f"Configuration error: {exc}", file=sys.stderr)
		return 1

	terminal_ui = TerminalUI.from_config(app_config)

	if app_config.drive_detection.collect_smart_info and not smartctl.is_smartctl_available():
		print(
			"Warning: SMART collection is enabled but 'smartctl' is not installed; SMART data will be unavailable.",
			file=sys.stderr,
		)

	terminal_ui.enter_alt_screen()
	dir_check.ensure_runtime_directories(app_config)

	try: 
		print(
			"Loaded configuration: "
			f"environment={app_config.runtime.environment}, "
			f"dry_run={app_config.runtime.dry_run}"
		)

		selected_drives = drive_detection.run(app_config, terminal_ui)
		if selected_drives == []:
			print("No drives detected.")
			return 1

		# if app_config.reporting.reports_enabled:
		# 	report_path = reporting.generate_detection_json_report(app_config, selected_drives)
		# 	print(f"Detection report written to: {report_path}")

		for drive in selected_drives:
			engine = wipe_engine.WipeEngine(drive, app_config.runtime.dry_run)
			result = engine.execute()
			print(f"Wipe result for {drive.path}: {result.status}")

	finally:
		terminal_ui.exit_alt_screen()

	return 0


if __name__ == "__main__":
	raise SystemExit(main())