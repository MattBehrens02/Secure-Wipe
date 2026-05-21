import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.terminal import (
    CommandRunnerError,
    CommandRunnerTimeout,
    TerminalUI,
    WipeCommands,
    run_command,
)


class TestTerminal(unittest.TestCase):
    @patch("modules.terminal.subprocess.run")
    def test_run_command_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo", "ok"],
            returncode=0,
            stdout="ok\n",
            stderr="",
        )
        result = run_command(["echo", "ok"], check=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ok\n")

    @patch("modules.terminal.subprocess.run")
    def test_run_command_raises_on_nonzero_when_check_true(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["badcmd"],
            returncode=2,
            stdout="",
            stderr="boom",
        )
        with self.assertRaises(CommandRunnerError):
            run_command(["badcmd"], check=True)

    @patch("modules.terminal.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1))
    def test_run_command_timeout(self, _mock_run):
        with self.assertRaises(CommandRunnerTimeout):
            run_command(["x"], timeout=1)

    def test_terminal_ui_from_config(self):
        dev_cfg = SimpleNamespace(runtime=SimpleNamespace(environment="dev"))
        prod_cfg = SimpleNamespace(runtime=SimpleNamespace(environment="prod"))
        self.assertFalse(TerminalUI.from_config(dev_cfg).interactive)
        self.assertTrue(TerminalUI.from_config(prod_cfg).interactive)

    @patch("modules.terminal.subprocess.run")
    def test_terminal_ui_noop_when_non_interactive(self, mock_run):
        ui = TerminalUI(interactive=False)
        ui.clear()
        ui.enter_alt_screen()
        ui.exit_alt_screen()
        mock_run.assert_not_called()

    def test_wipe_commands_build_expected_commands(self):
        self.assertIn("luksFormat", WipeCommands.luks_format("/dev/sda", "/tmp/key"))
        self.assertEqual(WipeCommands.luks_close("wipe_sda"), ["cryptsetup", "close", "wipe_sda"])
        self.assertEqual(
            WipeCommands.scrub("/dev/mapper/wipe_sda"),
            ["scrub", "-f", "-p", "nnsa", "/dev/mapper/wipe_sda"],
        )


if __name__ == "__main__":
    unittest.main()
