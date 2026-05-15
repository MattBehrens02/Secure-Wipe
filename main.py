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

	recovery_cfg = getattr(app_config, "recovery", object())
	lock_file_path = getattr(recovery_cfg, "lock_file_path", "./state/wipe.lock")
	lock_stale_seconds = int(getattr(recovery_cfg, "lock_stale_seconds", 7200))
	resume_max_age_seconds = int(getattr(recovery_cfg, "resume_state_max_age_seconds", 86400))
	allow_failed_resume = bool(getattr(recovery_cfg, "allow_failed_resume", False))
	state_dir = getattr(getattr(app_config, "paths", object()), "state_dir", "./state")

	lock_acquired, lock_error = recovery.acquire_lock(lock_file_path, stale_after_seconds=lock_stale_seconds)
	if not lock_acquired:
		print(f"Recovery lock error: {lock_error}", file=sys.stderr)
		app_logging.log_error(f"Recovery lock acquisition failed path={lock_file_path} error={lock_error}")
		terminal_ui.exit_alt_screen()
		return 1

	try: 
		incomplete_states = recovery.list_incomplete_states(state_dir)
		resume_candidates = [
			state
			for state in incomplete_states
			if recovery.should_offer_resume(
				state,
				max_age_seconds=resume_max_age_seconds,
				allow_failed_resume=allow_failed_resume,
			)
		]

		if resume_candidates:
			print(
				f"Found {len(resume_candidates)} resumable recovery state(s). "
				"Resume/restart flow will be enabled in next recovery integration step."
			)
			app_logging.log_info(f"Recovery detected resumable_states={len(resume_candidates)}")

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
			result = engine.execute_with_recovery(app_config)
			verification_result = None
			print(f"Wipe result for {drive.path}: {result.status}")
			if getattr(result, "recovery_resumed", False):
				resume_attempts = getattr(result, "recovery_resume_attempts", 0)
				resume_source = getattr(result, "recovery_resume_source_status", "unknown")
				print(
					f"Recovery state for {drive.path}: resumed from {resume_source} "
					f"(attempt {resume_attempts})"
				)
				app_logging.log_info(
					f"Recovery resumed drive={drive.path} source_status={resume_source} attempts={resume_attempts}"
				)
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
				verification_result = engine.verify_with_config(app_config)
				result.verification_result = verification_result
				print(f"Verification result for {drive.path}: {verification_result.status}")
				if verification_result.status == "failed":
					app_logging.log_error(
						f"Verification failed drive={drive.path} failed_checks={verification_result.checks_failed}"
					)
				else:
					app_logging.log_info(
						f"Verification completed drive={drive.path} status={verification_result.status}"
					)
			
			# Print duration summary if available
			duration_summary = getattr(result, "format_duration_summary", lambda: "")()
			if duration_summary:
				print(duration_summary)
			
			# Generate and save wipe report
			try:
				report = reporting.generate_wipe_report(
					drive,
					result,
					app_config,
					verification_result=verification_result,
				)
				reports_dir = getattr(app_config.paths, "reports_dir", "./reports")
				detail_level = getattr(app_config.reporting, "detail_level", "verbose")
				json_path, text_path = reporting.save_wipe_report(
					report,
					reports_dir,
					detail_level=detail_level,
				)
				print(f"\nWipe report saved:")
				print(f"  JSON: {json_path}")
				print(f"  Text: {text_path}")
				app_logging.log_info(f"Wipe report saved drive={drive.path} json={json_path} text={text_path}")
				
				# Attempt to upload reports
				upload_result = uploader.upload_reports(
					json_path,
					text_path,
					app_config,
					dry_run=app_config.runtime.dry_run,
				)
				if upload_result:
					print("Report upload: SUCCESS")
					app_logging.log_info(f"Report upload succeeded drive={drive.path}")
				else:
					print("Report upload: FAILED (reports retained locally for retry)")
					app_logging.log_error(f"Report upload failed drive={drive.path}; reports retained locally")
			except Exception as report_error:
				app_logging.log_error(f"Failed to save wipe report: {report_error}")

	finally:
		recovery.release_lock(lock_file_path)
		terminal_ui.exit_alt_screen()

	return 0


if __name__ == "__main__":
	raise SystemExit(main())