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


if __name__ == "__main__":
	unittest.main()