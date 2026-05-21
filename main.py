import sys
import tomllib
from types import SimpleNamespace

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header, dir_check, menu_shell
from modules import smartctl
from modules import app_logging
from modules.terminal import TerminalUI


SUBMENU_WIDTH = 80
REPORTS_PAGE_SIZE = 20


def _submenu_line() -> None:
	print("+" + "-" * (SUBMENU_WIDTH - 2) + "+")


def _print_submenu(title: str, options: list[str], footer: str) -> None:
	_submenu_line()
	title_content = f" {title} "
	title_padding = max(0, (SUBMENU_WIDTH - 2 - len(title_content)) // 2)
	print("|" + " " * title_padding + title_content.ljust(SUBMENU_WIDTH - 2 - title_padding) + "|")
	_submenu_line()
	for index, option in enumerate(options, start=1):
		label = f" [{index}] {option}"
		print("|" + label.ljust(SUBMENU_WIDTH - 2) + "|")
	_submenu_line()
	print("|" + f" {footer}".ljust(SUBMENU_WIDTH - 2) + "|")
	_submenu_line()


def _recovery_settings(app_config):
	recovery_cfg = getattr(app_config, "recovery", object())
	state_dir = getattr(getattr(app_config, "paths", object()), "state_dir", "./state")
	lock_file_path = getattr(recovery_cfg, "lock_file_path", "./state/wipe.lock")
	lock_stale_seconds = int(getattr(recovery_cfg, "lock_stale_seconds", 7200))
	resume_max_age_seconds = int(getattr(recovery_cfg, "resume_state_max_age_seconds", 86400))
	allow_failed_resume = bool(getattr(recovery_cfg, "allow_failed_resume", False))
	return state_dir, lock_file_path, lock_stale_seconds, resume_max_age_seconds, allow_failed_resume


def _clear_incomplete_states(state_dir: str) -> int:
	return recovery.clear_incomplete_states(state_dir)


def _pending_states(app_config) -> list[recovery.RecoveryState]:
	state_dir, _, _, resume_max_age_seconds, allow_failed_resume = _recovery_settings(app_config)
	incomplete_states = recovery.list_incomplete_states(state_dir)
	return [
		state
		for state in incomplete_states
		if recovery.should_offer_resume(
			state,
			max_age_seconds=resume_max_age_seconds,
			allow_failed_resume=allow_failed_resume,
		)
	]


def _select_restart_drive(app_config, terminal_ui: TerminalUI) -> list[object] | None:
	resume_candidates = _pending_states(app_config)

	if not resume_candidates:
		print("No pending jobs are available to restart.")
		app_logging.log_info("Restart pending jobs requested but no resumable states were found")
		return None

	resume_candidates_sorted = sorted(
		resume_candidates,
		key=lambda state: state.updated_at,
		reverse=True,
	)

	print("\nPending jobs:")
	for state in resume_candidates_sorted:
		print(
			f"  Drive: {state.drive_path}, Status: {state.status}, "
			f"Current step: {state.current_step}, Updated: {state.updated_at}"
		)

	choices = [f"Resume {state.drive_path}" for state in resume_candidates_sorted]
	while True:
		_print_submenu("Pending Jobs", choices, "Enter number or R to return")
		if not terminal_ui.interactive:
			selected_index = 0
			break
		user_input = input("Select pending job: ").strip()
		if user_input.lower() == "r":
			app_logging.log_info("User returned to main menu from pending restart list")
			return None
		if user_input.isdigit():
			selected_index = int(user_input) - 1
			if 0 <= selected_index < len(choices):
				break
		print("Invalid selection. Enter a listed number or R.")

	selected_state = resume_candidates_sorted[selected_index]
	metadata = selected_state.metadata if isinstance(selected_state.metadata, dict) else {}
	selected_drive = SimpleNamespace(
		path=selected_state.drive_path,
		name=metadata.get("drive_name", ""),
		model=metadata.get("drive_model", ""),
		vendor=metadata.get("drive_vendor", ""),
		serial=metadata.get("drive_serial", ""),
		size=metadata.get("drive_size", ""),
		type=metadata.get("drive_type", "disk"),
		mountpoints=list(metadata.get("drive_mountpoints", [])),
		removable=bool(metadata.get("drive_removable", False)),
		transport=metadata.get("drive_transport", ""),
		rotational=metadata.get("drive_rotational"),
		media_type=metadata.get("drive_media_type", "Unknown"),
		is_hdd=bool(metadata.get("drive_is_hdd", False)),
		smart_data=metadata.get("drive_smart_data"),
	)
	app_logging.log_info(f"User chose to restart wipe on {selected_drive.path}")
	return [selected_drive]


def _view_reports(app_config, terminal_ui: TerminalUI) -> None:
	reports_dir = getattr(getattr(app_config, "paths", object()), "reports_dir", "./reports")
	report_paths = reporting.list_saved_reports(reports_dir)

	if not report_paths:
		print(f"No reports found in {reports_dir}.")
		app_logging.log_info(f"Report viewer opened with no reports in {reports_dir}")
		return

	page_index = 0
	page_count = max(1, (len(report_paths) + REPORTS_PAGE_SIZE - 1) // REPORTS_PAGE_SIZE)
	while True:
		start = page_index * REPORTS_PAGE_SIZE
		end = start + REPORTS_PAGE_SIZE
		page_reports = report_paths[start:end]
		options = [path.name for path in page_reports]
		footer = f"Page {page_index + 1}/{page_count} - number to view, N/P to navigate, R to return"
		_print_submenu("Report Viewer", options, footer)

		if not terminal_ui.interactive:
			if not page_reports:
				return
			selected_path = page_reports[0]
		else:
			user_input = input("Select report: ").strip()
			lowered = user_input.lower()
			if lowered == "r":
				app_logging.log_info("User returned to main menu from report viewer")
				return
			if lowered == "n":
				if page_index < page_count - 1:
					page_index += 1
				continue
			if lowered == "p":
				if page_index > 0:
					page_index -= 1
				continue
			if not user_input.isdigit():
				print("Invalid selection. Enter a number, N, P, or R.")
				continue
			selected_index = int(user_input) - 1
			if selected_index < 0 or selected_index >= len(page_reports):
				print("Invalid selection. Enter a number from the current page.")
				continue
			selected_path = page_reports[selected_index]

		print("\n" + "=" * 80)
		print(f"REPORT: {selected_path.name}")
		print("=" * 80)
		try:
			print(reporting.read_saved_report(selected_path))
		except OSError as exc:
			print(f"Failed to read report {selected_path.name}: {exc}")
			app_logging.log_error(f"Report read failed path={selected_path} error={exc}")
		print("=" * 80)

		if terminal_ui.interactive:
			input("Press Enter to return to report list (or R at menu to exit)...")


def _configure_settings(app_config, terminal_ui: TerminalUI):
	while True:
		choices = [
			f"Toggle Dry Run (currently: {'ON' if app_config.runtime.dry_run else 'OFF'})",
			f"Toggle Upload Enabled (currently: {'ON' if app_config.upload.enabled else 'OFF'})",
			f"Toggle SMART Collection (currently: {'ON' if app_config.drive_detection.collect_smart_info else 'OFF'})",
			f"Toggle Logging Level (currently: {app_config.logging.level.upper()})",
			f"Cycle Report Detail Level (currently: {app_config.reporting.detail_level})",
		]
		_print_submenu("Configuration", choices, "Enter number or R to return")

		if not terminal_ui.interactive:
			selected_index = 0
		else:
			user_input = input("Select configuration action: ").strip()
			if user_input.lower() == "r":
				app_logging.log_info("User returned to main menu from configuration menu")
				return app_config
			if not user_input.isdigit():
				print("Invalid selection. Enter a number or R.")
				continue
			selected_index = int(user_input) - 1
			if selected_index < 0 or selected_index >= len(choices):
				print("Invalid selection. Enter a listed number or R.")
				continue

		choice = choices[selected_index]

		if choice.lower() == "r":
			app_logging.log_info("User returned to main menu from configuration menu")
			return app_config

		if choice.startswith("Toggle Dry Run"):
			app_config.runtime.dry_run = not app_config.runtime.dry_run
			print(f"Dry run is now {'ON' if app_config.runtime.dry_run else 'OFF'}.")
		elif choice.startswith("Toggle Upload Enabled"):
			app_config.upload.enabled = not app_config.upload.enabled
			print(f"Upload is now {'ON' if app_config.upload.enabled else 'OFF'}.")
		elif choice.startswith("Toggle SMART Collection"):
			app_config.drive_detection.collect_smart_info = not app_config.drive_detection.collect_smart_info
			print(
				"SMART collection is now "
				f"{'ON' if app_config.drive_detection.collect_smart_info else 'OFF'}."
			)
		elif choice.startswith("Toggle Logging Level"):
			app_config.logging.level = "errors" if app_config.logging.level == "info" else "info"
			print(f"Logging level is now {app_config.logging.level.upper()}.")
		elif choice.startswith("Cycle Report Detail Level"):
			detail_levels = ["minimal", "standard", "verbose"]
			current = app_config.reporting.detail_level
			if current not in detail_levels:
				current = "verbose"
			next_index = (detail_levels.index(current) + 1) % len(detail_levels)
			app_config.reporting.detail_level = detail_levels[next_index]
			print(f"Report detail level is now {app_config.reporting.detail_level}.")

		try:
			config.save_user_config(app_config)
			app_logging.log_info("Configuration updated from in-app configuration menu")
		except OSError as exc:
			print(f"Failed to save configuration: {exc}")
			app_logging.log_error(f"Failed to persist configuration changes: {exc}")


def _maintenance_menu(app_config, terminal_ui: TerminalUI) -> None:
	state_dir, lock_file_path, lock_stale_seconds, _, _ = _recovery_settings(app_config)

	choices = [
		f"Clear stale recovery lock ({lock_file_path})",
		f"Clear all incomplete recovery states ({state_dir})",
	]

	while True:
		_print_submenu("Maintenance", choices, "Enter number or R to return")

		if not terminal_ui.interactive:
			selected_index = 0
		else:
			user_input = input("Select maintenance action: ").strip()
			if user_input.lower() == "r":
				app_logging.log_info("User returned to main menu from maintenance menu")
				return
			if not user_input.isdigit():
				print("Invalid selection. Enter a number or R.")
				continue
			selected_index = int(user_input) - 1
			if selected_index < 0 or selected_index >= len(choices):
				print("Invalid selection. Enter a listed number or R.")
				continue

		confirmation = "CLEAR" if terminal_ui.interactive else "CLEAR"
		if terminal_ui.interactive:
			confirmation = input("Type CLEAR to confirm maintenance action (or anything else to cancel): ").strip()
		if confirmation != "CLEAR":
			print("Maintenance action cancelled.")
			continue

		if selected_index == 0:
			cleared, message = recovery.clear_stale_lock(lock_file_path, stale_after_seconds=lock_stale_seconds)
			print(message)
			if cleared:
				app_logging.log_info(f"Maintenance cleared stale lock path={lock_file_path}")
			else:
				app_logging.log_error(f"Maintenance stale lock clear skipped path={lock_file_path} reason={message}")
		elif selected_index == 1:
			cleared_count = _clear_incomplete_states(state_dir)
			print(f"Cleared {cleared_count} incomplete recovery state(s).")
			app_logging.log_info(f"Maintenance cleared {cleared_count} incomplete recovery state(s)")


def main(interactive: bool = False) -> int:
	try:
		app_config = config.load_config()
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		print(f"Configuration error: {exc}", file=sys.stderr)
		return 1

	terminal_ui = TerminalUI.from_config(app_config)
	interactive_menu = interactive and sys.stdin.isatty()
	state_dir, lock_file_path, lock_stale_seconds, _resume_max_age_seconds, _allow_failed_resume = _recovery_settings(app_config)

	terminal_ui.enter_alt_screen()
	try:
		while True:
			action_success = True
			selected_drives: list[object] = []

			while True:
				menu_choice = 1
				if interactive_menu:
					menu_choice = menu_shell.run()

				if menu_choice == -1:
					print("Exiting...")
					return 0
				if menu_choice not in {1, 2, 3, 4, 5}:
					print("Invalid menu selection.")
					return 1

				if menu_choice == 3:
					_view_reports(app_config, terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 4:
					app_config = _configure_settings(app_config, terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 5:
					_maintenance_menu(app_config, terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 1:
					pending_states = _pending_states(app_config)
					if pending_states:
						print(
							f"Warning: {len(pending_states)} pending job(s) exist. "
							"Starting a fresh job will clear those recovery states."
						)
						app_logging.log_info(
							f"Fresh start requested with {len(pending_states)} pending recovery state(s) present"
						)
					cleared_states = _clear_incomplete_states(state_dir)
					if cleared_states:
						app_logging.log_info(f"User chose fresh start; cleared {cleared_states} incomplete state(s)")
					break

				selected_drives = _select_restart_drive(app_config, terminal_ui) or []
				if not selected_drives:
					if interactive_menu:
						continue
					return 0
				break

			if app_config.drive_detection.collect_smart_info and not smartctl.is_smartctl_available():
				print(
					"Warning: SMART collection is enabled but 'smartctl' is not installed; SMART data will be unavailable.",
					file=sys.stderr,
				)
				app_logging.log_error("SMART collection enabled but smartctl is unavailable")

			dir_check.ensure_runtime_directories(app_config)
			app_logging.setup_logging(app_config)

			lock_acquired, lock_error = recovery.acquire_lock(lock_file_path, stale_after_seconds=lock_stale_seconds)
			if not lock_acquired:
				print(f"Recovery lock error: {lock_error}", file=sys.stderr)
				app_logging.log_error(f"Recovery lock acquisition failed path={lock_file_path} error={lock_error}")
				action_success = False
				if not interactive_menu:
					return 1
				print("Action result: FAILED. Returning to main menu...")
				continue

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

				if not selected_drives:
					selected_drives = drive_detection.run(app_config, terminal_ui)

				if selected_drives == []:
					print("No drives detected.")
					app_logging.log_error("No drives detected after selection flow")
					action_success = False

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
						action_success = False
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
							action_success = False
							app_logging.log_error(
								f"Verification failed drive={drive.path} failed_checks={verification_result.checks_failed}"
							)
						else:
							app_logging.log_info(
								f"Verification completed drive={drive.path} status={verification_result.status}"
							)

					duration_summary = getattr(result, "format_duration_summary", lambda: "")()
					if duration_summary:
						print(duration_summary)

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
						print("\nWipe report saved:")
						print(f"  JSON: {json_path}")
						print(f"  Text: {text_path}")
						app_logging.log_info(f"Wipe report saved drive={drive.path} json={json_path} text={text_path}")

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
							action_success = False
							print("Report upload: FAILED (reports retained locally for retry)")
							app_logging.log_error(f"Report upload failed drive={drive.path}; reports retained locally")
					except Exception as report_error:
						action_success = False
						app_logging.log_error(f"Failed to save wipe report: {report_error}")
			finally:
				recovery.release_lock(lock_file_path)

			if not interactive_menu:
				return 0 if action_success else 1

			status_text = "SUCCESS" if action_success else "FAILED"
			print(f"\nAction result: {status_text}. Returning to main menu...")
	finally:
		terminal_ui.exit_alt_screen()

	return 0


if __name__ == "__main__":
	raise SystemExit(main(interactive=True))
