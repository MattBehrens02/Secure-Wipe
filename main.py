import sys
import tomllib

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header, dir_check
from modules import smartctl
from modules import app_logging
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
		app_logging.log_error("SMART collection enabled but smartctl is unavailable")

	terminal_ui.enter_alt_screen()
	dir_check.ensure_runtime_directories(app_config)
	app_logging.setup_logging(app_config)

	try: 
		print(
			"Loaded configuration: "
			f"environment={app_config.runtime.environment}, "
			f"dry_run={app_config.runtime.dry_run}"
		)
		app_logging.log_info(
			"Application start "
			f"environment={app_config.runtime.environment} dry_run={app_config.runtime.dry_run}"
		)

		selected_drives = drive_detection.run(app_config, terminal_ui)
		if selected_drives == []:
			print("No drives detected.")
			app_logging.log_error("No drives detected after selection flow")
			return 1

		# if app_config.reporting.reports_enabled:
		# 	report_path = reporting.generate_detection_json_report(app_config, selected_drives)
		# 	print(f"Detection report written to: {report_path}")

		for drive in selected_drives:
			engine = wipe_engine.WipeEngine(drive, app_config.runtime.dry_run)
			result = engine.execute()
			print(f"Wipe result for {drive.path}: {result.status}")
			if result.status == "failed":
				failed_step = getattr(result, "failed_step", None)
				error_message = getattr(result, "error_message", None)
				app_logging.log_error(
					f"Wipe failed drive={drive.path} step={failed_step} error={error_message}"
				)
			else:
				started_at = getattr(result, "started_at", None)
				finished_at = getattr(result, "finished_at", None)
				app_logging.log_info(
					f"Wipe completed drive={drive.path} status={result.status} "
					f"started_at={started_at} finished_at={finished_at}"
				)
			
			# Print duration summary if available
			duration_summary = getattr(result, "format_duration_summary", lambda: "")()
			if duration_summary:
				print(duration_summary)

	finally:
		terminal_ui.exit_alt_screen()

	return 0


if __name__ == "__main__":
	raise SystemExit(main())