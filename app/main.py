import sys
import os
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine, header, dir_check, menu_shell
from modules import smartctl
from modules import app_logging
from modules.terminal import TerminalUI, get_adaptive_menu_width


SUBMENU_WIDTH_MIN = 88
SUBMENU_WIDTH_DEFAULT = 108
SUBMENU_WIDTH_MAX = 120
REPORTS_PAGE_SIZE = 20


def _append_menu_alert(menu_alerts: list[str], message: str) -> None:
	text = str(message).strip()
	if not text:
		return
	if text in menu_alerts:
		return
	menu_alerts.append(text)
	if len(menu_alerts) > 5:
		del menu_alerts[0]


def _load_runtime_config() -> tuple[config.AppConfig, str | None]:
	try:
		return config.load_config(), None
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		fallback = config.AppConfig()
		return fallback, f"Configuration error: {exc}. Using safe defaults until configuration is fixed."


def _normalize_nav_input(raw_value: str) -> str:
	return str(raw_value or "").strip().lower()


def _parse_submenu_input(
	raw_value: str,
	option_count: int,
	*,
	allow_paging: bool = False,
) -> tuple[str, int | None]:
	"""Parse shared submenu navigation commands.

	Returns:
		(action, selected_index)
		- action: one of 'select', 'back', 'next_page', 'prev_page', 'invalid'
		- selected_index: zero-based index when action == 'select', else None
	"""
	value = _normalize_nav_input(raw_value)
	if value in {"r", "b", "back", "return"}:
		return "back", None

	if allow_paging and value in {"n", "f", "next", "forward", ">"}:
		return "next_page", None
	if allow_paging and value in {"p", "prev", "previous", "<"}:
		return "prev_page", None

	if value.isdigit():
		selected_index = int(value) - 1
		if 0 <= selected_index < option_count:
			return "select", selected_index

	return "invalid", None


def _submenu_width() -> int:
	return get_adaptive_menu_width(
		min_width=SUBMENU_WIDTH_MIN,
		default_width=SUBMENU_WIDTH_DEFAULT,
		max_width=SUBMENU_WIDTH_MAX,
	)


def _submenu_line(width: int) -> None:
	print("+" + "-" * (width - 2) + "+")


def _submenu_row(width: int, text: str = "") -> None:
	print("|" + str(text)[: width - 2].ljust(width - 2) + "|")


def _submenu_section_title(width: int, title: str) -> None:
	content = f" {title} "
	padding = max(0, (width - 2 - len(content)) // 2)
	_submenu_row(width, " " * padding + content)


def _print_submenu(title: str, options: list[str], footer: str) -> None:
	width = _submenu_width()
	_submenu_line(width)
	_submenu_section_title(width, title)
	_submenu_line(width)
	_submenu_section_title(width, "Options")
	_submenu_line(width)
	for index, option in enumerate(options, start=1):
		label = f" [{index}] {option}"
		_submenu_row(width, label)
	_submenu_line(width)
	_submenu_section_title(width, "Navigation")
	_submenu_row(width, f" {footer}")
	_submenu_line(width)


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
		if getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod":
			terminal_ui.clear()
		_print_submenu("Pending Jobs", choices, "Enter number or B/R to return")
		if not terminal_ui.interactive:
			selected_index = 0
			break
		user_input = input("Select pending job: ").strip()
		action, selected_index = _parse_submenu_input(user_input, len(choices), allow_paging=False)
		if action == "back":
			app_logging.log_info("User returned to main menu from pending restart list")
			return None
		if action == "select" and selected_index is not None:
			break
		print("Invalid selection. Enter a listed number or B/R.")

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
		if getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod":
			terminal_ui.clear()
		start = page_index * REPORTS_PAGE_SIZE
		end = start + REPORTS_PAGE_SIZE
		page_reports = report_paths[start:end]
		options = [path.name for path in page_reports]
		footer = f"Page {page_index + 1}/{page_count} - number to view, N/P page, B/R return"
		_print_submenu("Report Viewer", options, footer)

		if not terminal_ui.interactive:
			if not page_reports:
				return
			selected_path = page_reports[0]
		else:
			user_input = input("Select report: ").strip()
			action, selected_index = _parse_submenu_input(user_input, len(page_reports), allow_paging=True)
			if action == "back":
				app_logging.log_info("User returned to main menu from report viewer")
				return
			if action == "next_page":
				if page_index < page_count - 1:
					page_index += 1
				continue
			if action == "prev_page":
				if page_index > 0:
					page_index -= 1
				continue
			if action != "select" or selected_index is None:
				print("Invalid selection. Enter a number, N/P for pages, or B/R to return.")
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


def _list_log_files(logs_dir: str) -> list[Path]:
	log_dir_path = Path(logs_dir)
	if not log_dir_path.exists():
		return []
	return sorted(
		[path for path in log_dir_path.iterdir() if path.is_file()],
		key=lambda path: path.stat().st_mtime,
		reverse=True,
	)


def _open_log_with_pager(log_path: Path, terminal_ui: TerminalUI) -> None:
	pager = os.environ.get("PAGER", "less")
	terminal_ui.exit_alt_screen()
	try:
		completed = subprocess.run([pager, str(log_path)], check=False)
		if completed.returncode != 0 and pager != "more":
			subprocess.run(["more", str(log_path)], check=False)
	except OSError as exc:
		print(f"Failed to open pager for {log_path.name}: {exc}")
		app_logging.log_error(f"Log pager open failed path={log_path} error={exc}")
	finally:
		terminal_ui.enter_alt_screen()


def _view_logs(app_config, terminal_ui: TerminalUI) -> None:
	logs_dir = getattr(getattr(app_config, "paths", object()), "logs_dir", "./logs")
	log_paths = _list_log_files(logs_dir)

	if not log_paths:
		print(f"No logs found in {logs_dir}.")
		app_logging.log_info(f"Log viewer opened with no logs in {logs_dir}")
		return

	page_index = 0
	page_count = max(1, (len(log_paths) + REPORTS_PAGE_SIZE - 1) // REPORTS_PAGE_SIZE)
	while True:
		if getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod":
			terminal_ui.clear()
		start = page_index * REPORTS_PAGE_SIZE
		end = start + REPORTS_PAGE_SIZE
		page_logs = log_paths[start:end]
		options = [path.name for path in page_logs]
		footer = f"Page {page_index + 1}/{page_count} - number to view, N/P page, B/R return"
		_print_submenu("Log Viewer", options, footer)

		if not terminal_ui.interactive:
			if not page_logs:
				return
			selected_path = page_logs[0]
		else:
			user_input = input("Select log: ").strip()
			action, selected_index = _parse_submenu_input(user_input, len(page_logs), allow_paging=True)
			if action == "back":
				app_logging.log_info("User returned to main menu from log viewer")
				return
			if action == "next_page":
				if page_index < page_count - 1:
					page_index += 1
				continue
			if action == "prev_page":
				if page_index > 0:
					page_index -= 1
				continue
			if action != "select" or selected_index is None:
				print("Invalid selection. Enter a number, N/P for pages, or B/R to return.")
				continue
			selected_path = page_logs[selected_index]

		app_logging.log_info(f"User opened log file in viewer path={selected_path}")
		_open_log_with_pager(selected_path, terminal_ui)


def _configure_settings(app_config, terminal_ui: TerminalUI):
	wipe_cfg = getattr(app_config, "wipe", None)
	if wipe_cfg is None:
		wipe_cfg = SimpleNamespace(container_scrub_pattern="fillzero", hdd_final_scrub_pattern="fillzero")
		app_config.wipe = wipe_cfg

	reporting_cfg = getattr(app_config, "reporting", None)
	if reporting_cfg is None:
		reporting_cfg = SimpleNamespace(detail_level="verbose", operator_identifier="unknown")
		app_config.reporting = reporting_cfg
	elif not hasattr(reporting_cfg, "operator_identifier"):
		reporting_cfg.operator_identifier = "unknown"

	pattern_order = ["fillzero", "random", "nnsa", "dod"]
	valid_log_levels = {"info", "errors"}

	def _warn_prefix(condition: bool) -> str:
		return "! " if condition else ""

	def _cycle_pattern(current_value: str) -> str:
		current_normalized = str(current_value).strip().lower()
		if current_normalized not in pattern_order:
			return pattern_order[0]
		next_index = (pattern_order.index(current_normalized) + 1) % len(pattern_order)
		return pattern_order[next_index]

	while True:
		if getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod":
			terminal_ui.clear()
		dry_run_risky = not bool(app_config.runtime.dry_run)
		upload_repo_missing = bool(app_config.upload.enabled) and not str(app_config.upload.repo or "").strip()
		smart_unavailable = bool(app_config.drive_detection.collect_smart_info) and not smartctl.is_smartctl_available()
		invalid_logging_level = str(app_config.logging.level).lower() not in valid_log_levels
		invalid_report_detail = str(app_config.reporting.detail_level).lower() not in {"minimal", "standard", "verbose"}
		choices = [
			f"{_warn_prefix(dry_run_risky)}Toggle Dry Run (currently: {'ON' if app_config.runtime.dry_run else 'OFF'})",
			f"{_warn_prefix(upload_repo_missing)}Toggle Upload Enabled (currently: {'ON' if app_config.upload.enabled else 'OFF'})",
			f"{_warn_prefix(smart_unavailable)}Toggle SMART Collection (currently: {'ON' if app_config.drive_detection.collect_smart_info else 'OFF'})",
			f"{_warn_prefix(invalid_logging_level)}Toggle Logging Level (currently: {app_config.logging.level.upper()})",
			f"{_warn_prefix(invalid_report_detail)}Cycle Report Detail Level (currently: {app_config.reporting.detail_level})",
			f"Set Operator Identifier (currently: {app_config.reporting.operator_identifier})",
			f"Cycle Container Scrub Pattern (currently: {wipe_cfg.container_scrub_pattern})",
			f"Cycle HDD Final Pattern (currently: {wipe_cfg.hdd_final_scrub_pattern})",
		]
		if any((dry_run_risky, upload_repo_missing, smart_unavailable, invalid_logging_level, invalid_report_detail)):
			print("! Marked options need attention before production runs.")
		_print_submenu("Configuration", choices, "Enter number or B/R to return")

		if not terminal_ui.interactive:
			selected_index = 0
		else:
			user_input = input("Select configuration action: ").strip()
			action, selected_index = _parse_submenu_input(user_input, len(choices), allow_paging=False)
			if action == "back":
				app_logging.log_info("User returned to main menu from configuration menu")
				return app_config
			if action != "select" or selected_index is None:
				print("Invalid selection. Enter a number or B/R.")
				continue

		if selected_index == 0:
			app_config.runtime.dry_run = not app_config.runtime.dry_run
			print(f"Dry run is now {'ON' if app_config.runtime.dry_run else 'OFF'}.")
		elif selected_index == 1:
			app_config.upload.enabled = not app_config.upload.enabled
			print(f"Upload is now {'ON' if app_config.upload.enabled else 'OFF'}.")
		elif selected_index == 2:
			app_config.drive_detection.collect_smart_info = not app_config.drive_detection.collect_smart_info
			print(
				"SMART collection is now "
				f"{'ON' if app_config.drive_detection.collect_smart_info else 'OFF'}."
			)
		elif selected_index == 3:
			app_config.logging.level = "errors" if app_config.logging.level == "info" else "info"
			print(f"Logging level is now {app_config.logging.level.upper()}.")
		elif selected_index == 4:
			detail_levels = ["minimal", "standard", "verbose"]
			current = app_config.reporting.detail_level
			if current not in detail_levels:
				current = "verbose"
			next_index = (detail_levels.index(current) + 1) % len(detail_levels)
			app_config.reporting.detail_level = detail_levels[next_index]
			print(f"Report detail level is now {app_config.reporting.detail_level}.")
		elif selected_index == 5:
			if not terminal_ui.interactive:
				print("Operator identifier can only be set interactively.")
				continue
			new_value = input("Enter operator identifier: ").strip()
			if not new_value:
				print("Operator identifier cannot be empty.")
				continue
			app_config.reporting.operator_identifier = new_value
			print(f"Operator identifier is now {app_config.reporting.operator_identifier}.")
		elif selected_index == 6:
			wipe_cfg.container_scrub_pattern = _cycle_pattern(wipe_cfg.container_scrub_pattern)
			print(f"Container scrub pattern is now {wipe_cfg.container_scrub_pattern}.")
		elif selected_index == 7:
			wipe_cfg.hdd_final_scrub_pattern = _cycle_pattern(wipe_cfg.hdd_final_scrub_pattern)
			print(f"HDD final scrub pattern is now {wipe_cfg.hdd_final_scrub_pattern}.")

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
		if getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod":
			terminal_ui.clear()
		_print_submenu("Maintenance", choices, "Enter number or B/R to return")

		if not terminal_ui.interactive:
			selected_index = 0
		else:
			user_input = input("Select maintenance action: ").strip()
			action, selected_index = _parse_submenu_input(user_input, len(choices), allow_paging=False)
			if action == "back":
				app_logging.log_info("User returned to main menu from maintenance menu")
				return
			if action != "select" or selected_index is None:
				print("Invalid selection. Enter a number or B/R.")
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


def _open_operator_shell(terminal_ui: TerminalUI) -> None:
	"""Temporarily drop to operator shell and return to app on exit."""
	shell = os.environ.get("SHELL", "/bin/bash")

	terminal_ui.exit_alt_screen()
	try:
		print("Opening terminal. Type 'exit' to return to Secure-Wipe.")
		completed = subprocess.run([shell], check=False)
		if completed.returncode != 0:
			print(f"Terminal exited with status {completed.returncode}.")
	except OSError as exc:
		print(f"Failed to open terminal: {exc}")
		app_logging.log_error(f"Operator shell launch failed: {exc}")
	finally:
		terminal_ui.enter_alt_screen()


def _request_system_power_action(
	action_label: str,
	systemctl_action: str,
	terminal_ui: TerminalUI,
) -> bool:
	print(f"{action_label} requested. Handing off to systemctl {systemctl_action}...")
	app_logging.log_info(f"System {action_label.lower()} requested from main menu")
	terminal_ui.exit_alt_screen()
	try:
		completed = subprocess.run(["systemctl", systemctl_action], check=False)
	except OSError as exc:
		print(f"Failed to {action_label.lower()} system: {exc}")
		app_logging.log_error(f"System {action_label.lower()} failed to start: {exc}")
		terminal_ui.enter_alt_screen()
		return False

	if completed.returncode != 0:
		print(f"Failed to {action_label.lower()} system: systemctl exited with status {completed.returncode}.")
		app_logging.log_error(
			f"System {action_label.lower()} failed: systemctl {systemctl_action} exited with status {completed.returncode}"
		)
		terminal_ui.enter_alt_screen()
		return False

	return True


def main(interactive: bool = False) -> int:
	menu_alerts: list[str] = []
	app_config, startup_config_error = _load_runtime_config()
	if startup_config_error:
		print(startup_config_error, file=sys.stderr)
		_append_menu_alert(menu_alerts, startup_config_error)

	terminal_ui = TerminalUI.from_config(app_config)
	interactive_menu = interactive and sys.stdin.isatty()
	startup_upload_flushed = False

	terminal_ui.enter_alt_screen()
	try:
		while True:
			action_success = True
			selected_drives: list[object] = []
			state_dir, lock_file_path, lock_stale_seconds, _resume_max_age_seconds, _allow_failed_resume = _recovery_settings(app_config)

			while True:
				menu_choice = 1
				if interactive_menu:
					menu_choice = menu_shell.run(app_config=app_config, alerts=menu_alerts)

				if menu_choice == -1:
					print("Exiting...")
					return 0
				if menu_choice not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
					print("Invalid menu selection.")
					return 1

				if menu_choice == 3:
					_view_reports(app_config, terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 4:
					app_config = _configure_settings(app_config, terminal_ui)
					reloaded_config, reload_error = _load_runtime_config()
					if reload_error:
						_append_menu_alert(menu_alerts, reload_error)
					else:
						app_config = reloaded_config
						menu_alerts = [message for message in menu_alerts if not message.startswith("Configuration error:")]
					if interactive_menu:
						continue
					return 0

				if menu_choice == 5:
					_maintenance_menu(app_config, terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 6:
					_open_operator_shell(terminal_ui)
					if interactive_menu:
						continue
					return 0

				if menu_choice == 7:
					shutdown_started = _request_system_power_action(
						"SHUTDOWN",
						"poweroff",
						terminal_ui,
					)
					if shutdown_started:
						return 0
					if interactive_menu:
						continue
					return 1

				if menu_choice == 8:
					restart_started = _request_system_power_action(
						"RESTART",
						"reboot",
						terminal_ui,
					)
					if restart_started:
						return 0
					if interactive_menu:
						continue
					return 1

				if menu_choice == 9:
					_view_logs(app_config, terminal_ui)
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
				smart_warning = "SMART collection is enabled but 'smartctl' is not installed; SMART data will be unavailable."
				print(f"Warning: {smart_warning}", file=sys.stderr)
				app_logging.log_error("SMART collection enabled but smartctl is unavailable")
				_append_menu_alert(menu_alerts, smart_warning)

			dir_check.ensure_runtime_directories(app_config)
			app_logging.setup_logging(app_config)

			if not startup_upload_flushed:
				startup_upload_flushed = True
				flushed = uploader.flush_pending_reports(
					app_config,
					dry_run=app_config.runtime.dry_run,
				)
				if not flushed:
					print("Warning: pending report upload flush failed; queued reports will be retried later.")
					app_logging.log_error("Startup pending report flush failed")
					_append_menu_alert(menu_alerts, "Pending report upload flush failed at startup.")

			lock_acquired, lock_error = recovery.acquire_lock(lock_file_path, stale_after_seconds=lock_stale_seconds)
			if not lock_acquired:
				print(f"Recovery lock error: {lock_error}", file=sys.stderr)
				app_logging.log_error(f"Recovery lock acquisition failed path={lock_file_path} error={lock_error}")
				_append_menu_alert(menu_alerts, f"Recovery lock error: {lock_error}")
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
					_append_menu_alert(menu_alerts, "No drives detected during selection flow.")
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
							app_config=app_config,
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
							_append_menu_alert(menu_alerts, f"Report upload failed for {drive.path}; retained for retry.")
					except Exception as report_error:
						action_success = False
						app_logging.log_error(f"Failed to save wipe report: {report_error}")
						_append_menu_alert(menu_alerts, f"Failed to save report for {drive.path}: {report_error}")
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
