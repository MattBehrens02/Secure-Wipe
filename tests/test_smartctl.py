import unittest
from unittest.mock import patch

from modules import smartctl
from modules.terminal import CommandResult


class TestSmartctl(unittest.TestCase):
    @patch("modules.smartctl.shutil.which", return_value="/usr/sbin/smartctl")
    def test_is_smartctl_available_true(self, _mock_which):
        self.assertTrue(smartctl.is_smartctl_available())

    @patch("modules.smartctl.run_command")
    def test_collect_smart_info_parses_json(self, mock_run):
        mock_run.return_value = CommandResult(
            args=["smartctl"],
            returncode=0,
            stdout='{"device": {"name": "sda"}}',
            stderr="",
        )
        data = smartctl.collect_smart_info("/dev/sda")
        self.assertEqual(data["device"]["name"], "sda")

    @patch("modules.smartctl.run_command")
    def test_collect_smart_info_nonzero_adds_metadata(self, mock_run):
        mock_run.return_value = CommandResult(
            args=["smartctl"],
            returncode=2,
            stdout='{"base": true}',
            stderr="disk warning",
        )
        data = smartctl.collect_smart_info("/dev/sda")
        self.assertEqual(data["smartctl_returncode"], 2)
        self.assertEqual(data["smartctl_error"], "disk warning")

    @patch("modules.smartctl.collect_smart_info", side_effect=[{"ok": True}, smartctl.SmartctlError("x")])
    def test_collect_smart_snapshot_fail_open(self, _mock_collect):
        snapshot = smartctl.collect_smart_snapshot(["/dev/sda", "/dev/sdb"])
        self.assertEqual(snapshot["/dev/sda"], {"ok": True})
        self.assertIsNone(snapshot["/dev/sdb"])


if __name__ == "__main__":
    unittest.main()
