import io
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from modules import dir_check, header


class TestUtilitiesAndMain(unittest.TestCase):
    def test_header_prints_banner(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            header.print_header()
        self.assertIn("_____", buf.getvalue())

    def test_ensure_runtime_directories_creates_missing_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = SimpleNamespace(
                paths=SimpleNamespace(
                    logs_dir=f"{tmp}/logs",
                    reports_dir=f"{tmp}/reports",
                    state_dir=f"{tmp}/state",
                    temp_dir=f"{tmp}/tmp",
                )
            )
            dir_check.ensure_runtime_directories(cfg)

            self.assertTrue((__import__("pathlib").Path(cfg.paths.logs_dir)).exists())
            self.assertTrue((__import__("pathlib").Path(cfg.paths.reports_dir)).exists())
            self.assertTrue((__import__("pathlib").Path(cfg.paths.state_dir)).exists())
            self.assertTrue((__import__("pathlib").Path(cfg.paths.temp_dir)).exists())

    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("main.smartctl.is_smartctl_available", return_value=True)
    @patch("main.dir_check.ensure_runtime_directories")
    @patch("main.drive_detection.run", return_value=[])
    def test_main_returns_one_when_no_drives(
        self,
        _mock_detect,
        _mock_dirs,
        _mock_smartctl,
        mock_ui_from_config,
        mock_load_config,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
        )
        mock_load_config.return_value = cfg
        mock_ui = Mock()
        mock_ui_from_config.return_value = mock_ui

        rc = main.main()
        self.assertEqual(rc, 1)
        mock_ui.enter_alt_screen.assert_called_once()
        mock_ui.exit_alt_screen.assert_called_once()

    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("main.smartctl.is_smartctl_available", return_value=True)
    @patch("main.dir_check.ensure_runtime_directories")
    @patch("main.drive_detection.run")
    @patch("main.reporting.save_wipe_report", return_value=("/tmp/report.json", "/tmp/report.txt"))
    @patch("main.reporting.generate_wipe_report", return_value=SimpleNamespace())
    @patch("main.wipe_engine.WipeEngine")
    def test_main_success_flow_runs_engine_for_each_drive(
        self,
        mock_engine_cls,
        _mock_generate_report,
        _mock_save_report,
        mock_detect,
        _mock_dirs,
        _mock_smartctl,
        mock_ui_from_config,
        mock_load_config,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            reporting=SimpleNamespace(detail_level="verbose", operator_identifier="test-operator"),
            paths=SimpleNamespace(reports_dir="/tmp"),
            verification=SimpleNamespace(enabled=True),
        )
        mock_load_config.return_value = cfg
        mock_ui_from_config.return_value = Mock()

        drive_a = SimpleNamespace(path="/dev/sda")
        drive_b = SimpleNamespace(path="/dev/sdb")
        mock_detect.return_value = [drive_a, drive_b]

        engine_instance = Mock()
        engine_instance.verify_with_config.return_value = SimpleNamespace(
            status="dry_run",
            checks_failed=[],
            checks_passed=["luks_header_destroyed"],
            verification_errors=[],
        )
        engine_instance.execute_with_recovery.side_effect = [
            SimpleNamespace(status="dry_run"),
            SimpleNamespace(status="dry_run"),
        ]
        mock_engine_cls.return_value = engine_instance

        rc = main.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mock_engine_cls.call_count, 2)
        self.assertEqual(engine_instance.verify_with_config.call_count, 2)

    @patch("main.sys.stdin.isatty", return_value=True)
    @patch("main.menu_shell.run", side_effect=[2, -1])
    @patch("builtins.input", return_value="1")
    @patch("main.recovery.release_lock")
    @patch("main.recovery.acquire_lock", return_value=(True, None))
    @patch("main.recovery.should_offer_resume", return_value=True)
    @patch("main.recovery.list_incomplete_states")
    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("main.smartctl.is_smartctl_available", return_value=True)
    @patch("main.dir_check.ensure_runtime_directories")
    @patch("main.drive_detection.run")
    @patch("main.reporting.save_wipe_report", return_value=("/tmp/report.json", "/tmp/report.txt"))
    @patch("main.reporting.generate_wipe_report", return_value=SimpleNamespace())
    @patch("main.wipe_engine.WipeEngine")
    def test_main_restart_pending_jobs_uses_recovery_state_drive(
        self,
        mock_engine_cls,
        _mock_generate_report,
        _mock_save_report,
        mock_detect,
        _mock_dirs,
        _mock_smartctl,
        mock_ui_from_config,
        mock_load_config,
        mock_list_states,
        _mock_should_offer_resume,
        mock_acquire_lock,
        mock_release_lock,
        _mock_input,
        mock_menu_run,
        _mock_isatty,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            reporting=SimpleNamespace(detail_level="verbose", operator_identifier="test-operator"),
            paths=SimpleNamespace(reports_dir="/tmp", state_dir="/tmp/state"),
            verification=SimpleNamespace(enabled=True),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
        )
        mock_load_config.return_value = cfg

        mock_ui = Mock(interactive=True)
        mock_ui_from_config.return_value = mock_ui

        pending_state = SimpleNamespace(
            drive_path="/dev/sda",
            status="interrupted",
            current_step="open_encrypted_container",
            updated_at="2026-05-19T10:00:00+00:00",
            metadata={"drive_is_hdd": False},
        )
        mock_list_states.return_value = [pending_state]

        engine_instance = Mock()
        engine_instance.verify_with_config.return_value = SimpleNamespace(
            status="dry_run",
            checks_failed=[],
            checks_passed=["luks_header_destroyed"],
            verification_errors=[],
        )
        engine_instance.execute_with_recovery.return_value = SimpleNamespace(status="dry_run")
        mock_engine_cls.return_value = engine_instance

        rc = main.main(interactive=True)
        self.assertEqual(rc, 0)
        self.assertEqual(mock_menu_run.call_count, 2)
        mock_detect.assert_not_called()
        self.assertEqual(mock_engine_cls.call_count, 1)
        self.assertEqual(getattr(mock_engine_cls.call_args.args[0], "path", None), "/dev/sda")
        mock_release_lock.assert_called_once_with("/tmp/state/wipe.lock")

    @patch("main.sys.stdin.isatty", return_value=True)
    @patch("main.menu_shell.run", side_effect=[2, -1])
    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("main.recovery.list_incomplete_states", return_value=[])
    def test_restart_returns_to_menu_when_no_pending_jobs(
        self,
        _mock_list_states,
        mock_ui_from_config,
        mock_load_config,
        mock_menu_run,
        _mock_isatty,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            paths=SimpleNamespace(state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
        )
        mock_load_config.return_value = cfg
        mock_ui_from_config.return_value = Mock()

        rc = main.main(interactive=True)
        self.assertEqual(rc, 0)
        self.assertEqual(mock_menu_run.call_count, 2)

    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("main.smartctl.is_smartctl_available", return_value=True)
    @patch("main.dir_check.ensure_runtime_directories")
    @patch("main.recovery.acquire_lock", return_value=(True, None))
    @patch("main.recovery.release_lock")
    @patch("main.recovery.should_offer_resume", return_value=True)
    @patch("main.recovery.list_incomplete_states")
    @patch("main.drive_detection.run", return_value=[])
    def test_main_warns_when_starting_with_pending_states(
        self,
        mock_detect,
        mock_list_states,
        _mock_should_offer_resume,
        mock_release_lock,
        mock_acquire_lock,
        _mock_dirs,
        _mock_smartctl,
        mock_ui_from_config,
        mock_load_config,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            paths=SimpleNamespace(state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
            reporting=SimpleNamespace(detail_level="verbose"),
        )
        mock_load_config.return_value = cfg
        mock_ui_from_config.return_value = Mock()
        mock_list_states.return_value = [
            SimpleNamespace(
                drive_path="/dev/sda",
                status="interrupted",
                current_step="open_encrypted_container",
                updated_at="2026-05-19T10:00:00+00:00",
                metadata={"drive_is_hdd": False},
            )
        ]

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main.main()

        self.assertEqual(rc, 1)
        self.assertIn("Warning: 1 pending job(s) exist.", buf.getvalue())
        mock_detect.assert_called_once()
        mock_acquire_lock.assert_called_once()
        mock_release_lock.assert_called_once()

    def test_placeholder_modules_import(self):
        import modules.recovery  # noqa: F401
        import modules.uploader  # noqa: F401
        import modules.verification  # noqa: F401

    @patch("main.sys.stdin.isatty", return_value=True)
    @patch("main.menu_shell.run", side_effect=[3, -1])
    @patch("main.reporting.list_saved_reports", return_value=[])
    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    def test_main_view_reports_handles_empty_report_directory(
        self,
        mock_ui_from_config,
        mock_load_config,
        mock_list_reports,
        _mock_menu_run,
        _mock_isatty,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            paths=SimpleNamespace(reports_dir="/tmp/reports", state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
        )
        mock_load_config.return_value = cfg
        mock_ui_from_config.return_value = Mock(interactive=True)

        rc = main.main(interactive=True)
        self.assertEqual(rc, 0)
        mock_list_reports.assert_called_once_with("/tmp/reports")

    @patch("main.sys.stdin.isatty", return_value=True)
    @patch("main.menu_shell.run", side_effect=[3, -1])
    @patch("main.reporting.read_saved_report", return_value="report body")
    @patch("main.reporting.list_saved_reports")
    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("builtins.input", side_effect=["1", "", "r"])
    def test_main_view_reports_displays_selected_report(
        self,
        _mock_pause,
        mock_ui_from_config,
        mock_load_config,
        mock_list_reports,
        mock_read_report,
        _mock_menu_run,
        _mock_isatty,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            drive_detection=SimpleNamespace(collect_smart_info=False),
            paths=SimpleNamespace(reports_dir="/tmp/reports", state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
        )
        mock_load_config.return_value = cfg

        mock_ui_from_config.return_value = Mock(interactive=True)

        mock_list_reports.return_value = [__import__("pathlib").Path("/tmp/reports/sample.txt")]

        rc = main.main(interactive=True)
        self.assertEqual(rc, 0)
        mock_read_report.assert_called_once()

    @patch("main.sys.stdin.isatty", return_value=True)
    @patch("main.menu_shell.run", side_effect=[4, -1])
    @patch("main.config.save_user_config")
    @patch("main.config.load_config")
    @patch("main.TerminalUI.from_config")
    @patch("builtins.input", side_effect=["1", "r"])
    def test_main_configuration_menu_persists_toggle_changes(
        self,
        _mock_input,
        mock_ui_from_config,
        mock_load_config,
        mock_save_config,
        _mock_menu_run,
        _mock_isatty,
    ):
        cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            upload=SimpleNamespace(enabled=False),
            drive_detection=SimpleNamespace(collect_smart_info=True),
            logging=SimpleNamespace(level="info"),
            reporting=SimpleNamespace(detail_level="verbose"),
            paths=SimpleNamespace(reports_dir="/tmp/reports", state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                lock_file_path="/tmp/state/wipe.lock",
                lock_stale_seconds=7200,
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
            ),
        )
        mock_load_config.return_value = cfg

        mock_ui_from_config.return_value = Mock(interactive=True)

        rc = main.main(interactive=True)
        self.assertEqual(rc, 0)
        self.assertFalse(cfg.runtime.dry_run)
        mock_save_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
