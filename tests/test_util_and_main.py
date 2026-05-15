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
    @patch("main.wipe_engine.WipeEngine")
    def test_main_success_flow_runs_engine_for_each_drive(
        self,
        mock_engine_cls,
        mock_detect,
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
        mock_ui_from_config.return_value = Mock()

        drive_a = SimpleNamespace(path="/dev/sda")
        drive_b = SimpleNamespace(path="/dev/sdb")
        mock_detect.return_value = [drive_a, drive_b]

        engine_instance = Mock()
        engine_instance.execute.side_effect = [
            SimpleNamespace(status="dry_run"),
            SimpleNamespace(status="dry_run"),
        ]
        mock_engine_cls.return_value = engine_instance

        rc = main.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mock_engine_cls.call_count, 2)

    def test_placeholder_modules_import(self):
        import modules.recovery  # noqa: F401
        import modules.uploader  # noqa: F401
        import modules.verification  # noqa: F401


if __name__ == "__main__":
    unittest.main()
