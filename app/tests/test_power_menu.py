import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app.main as main
from modules import menu_shell


class TestPowerMenu(unittest.TestCase):
	def test_menu_shell_accepts_shutdown_option(self):
		with patch("builtins.input", return_value="7"):
			self.assertEqual(menu_shell.run(), 7)

	def test_menu_shell_accepts_restart_option(self):
		with patch("builtins.input", return_value="8"):
			self.assertEqual(menu_shell.run(), 8)

	def test_menu_shell_accepts_view_logs_option(self):
		with patch("builtins.input", return_value="9"):
			self.assertEqual(menu_shell.run(), 9)

	def test_menu_shell_rejects_q_and_reprompts(self):
		with patch("builtins.input", side_effect=["q", "9"]):
			self.assertEqual(menu_shell.run(), 9)

	@patch("main.sys.stdin.isatty", return_value=True)
	@patch("main.menu_shell.run", return_value=7)
	@patch("main.subprocess.run", return_value=SimpleNamespace(returncode=0))
	@patch("main.config.load_config")
	@patch("main.TerminalUI.from_config")
	def test_main_shutdown_action_invokes_systemctl_poweroff(
		self,
		mock_ui_from_config,
		mock_load_config,
		mock_subprocess_run,
		_mock_menu_run,
		_mock_isatty,
	):
		cfg = SimpleNamespace(
			runtime=SimpleNamespace(environment="test", dry_run=True),
		)
		mock_load_config.return_value = cfg
		mock_ui = Mock(interactive=True)
		mock_ui_from_config.return_value = mock_ui

		rc = main.main(interactive=True)

		self.assertEqual(rc, 0)
		mock_subprocess_run.assert_called_once_with(["systemctl", "poweroff"], check=False)
		mock_ui.exit_alt_screen.assert_called()

	@patch("main.sys.stdin.isatty", return_value=True)
	@patch("main.menu_shell.run", return_value=8)
	@patch("main.subprocess.run", return_value=SimpleNamespace(returncode=0))
	@patch("main.config.load_config")
	@patch("main.TerminalUI.from_config")
	def test_main_restart_action_invokes_systemctl_reboot(
		self,
		mock_ui_from_config,
		mock_load_config,
		mock_subprocess_run,
		_mock_menu_run,
		_mock_isatty,
	):
		cfg = SimpleNamespace(
			runtime=SimpleNamespace(environment="test", dry_run=True),
		)
		mock_load_config.return_value = cfg
		mock_ui = Mock(interactive=True)
		mock_ui_from_config.return_value = mock_ui

		rc = main.main(interactive=True)

		self.assertEqual(rc, 0)
		mock_subprocess_run.assert_called_once_with(["systemctl", "reboot"], check=False)
		mock_ui.exit_alt_screen.assert_called()

	@patch("main.sys.stdin.isatty", return_value=True)
	@patch("main.menu_shell.run", side_effect=[9, -1])
	@patch("main.config.load_config")
	@patch("main.TerminalUI.from_config")
	def test_main_view_logs_option_invokes_log_viewer(
		self,
		mock_ui_from_config,
		mock_load_config,
		_mock_menu_run,
		_mock_isatty,
	):
		cfg = SimpleNamespace(
			runtime=SimpleNamespace(environment="test", dry_run=True),
		)
		mock_load_config.return_value = cfg
		mock_ui_from_config.return_value = Mock(interactive=True)

		with patch.object(main, "_view_logs") as mock_view_logs:
			rc = main.main(interactive=True)

		self.assertEqual(rc, 0)
		mock_view_logs.assert_called_once()

	@patch("main.sys.stdin.isatty", return_value=True)
	@patch("main.menu_shell.run", side_effect=[9, -1])
	@patch("main.config.load_config", side_effect=ValueError("bad config"))
	@patch("main.TerminalUI.from_config")
	def test_main_recovers_with_safe_defaults_when_config_is_invalid(
		self,
		mock_ui_from_config,
		_mock_load_config,
		_mock_menu_run,
		_mock_isatty,
	):
		mock_ui_from_config.return_value = Mock(interactive=True)

		with patch.object(main, "_view_logs") as mock_view_logs:
			rc = main.main(interactive=True)

		self.assertEqual(rc, 0)
		mock_view_logs.assert_called_once()


if __name__ == "__main__":
	unittest.main()