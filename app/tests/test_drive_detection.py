import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.drive_detection import (
    Drive,
    DriveDetectionError,
    _apply_safety_policy,
    _coerce_rotational,
    confirm_all_drives,
    detect_drives,
    get_user_input,
    normalize_drive_data,
    normalize_drives,
)
from modules.terminal import CommandResult, CommandRunnerTimeout


class TestDriveDetection(unittest.TestCase):
    def test_coerce_rotational(self):
        self.assertTrue(_coerce_rotational("1"))
        self.assertFalse(_coerce_rotational("no"))
        self.assertIsNone(_coerce_rotational("unknown"))

    def test_normalize_drive_data_ignores_non_disk(self):
        self.assertIsNone(normalize_drive_data({"type": "part"}))

    def test_normalize_drives_happy_path(self):
        payload = {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "size": "1000000000000",
                    "model": "Disk",
                    "vendor": "Vendor",
                    "serial": "SER",
                    "type": "disk",
                    "mountpoints": [None, "/mnt"],
                    "rm": 0,
                    "tran": "sata",
                    "rota": 1,
                }
            ]
        }
        drives = normalize_drives(payload)
        self.assertEqual(len(drives), 1)
        self.assertEqual(drives[0].path, "/dev/sda")
        self.assertEqual(drives[0].mountpoints, ["/mnt"])
        self.assertEqual(drives[0].size_bytes, 1000000000000)
        self.assertEqual(drives[0].size, "1.0T")

    def test_apply_safety_policy_filters_removable_and_mounted(self):
        cfg = SimpleNamespace(
            safety=SimpleNamespace(removable_drive_mode="deny", mount_handling_mode="deny")
        )
        drives = [
            Drive("a", "/dev/sda", "1T", "", "", "", "disk", [], False, "sata", True),
            Drive("b", "/dev/sdb", "1T", "", "", "", "disk", ["/mnt"], False, "usb", False),
            Drive("c", "/dev/sdc", "1T", "", "", "", "disk", [], True, "usb", False),
        ]
        eligible = _apply_safety_policy(drives, cfg)
        self.assertEqual([d.path for d in eligible], ["/dev/sda"])

    @patch("modules.drive_detection.run_command")
    def test_detect_drives_success(self, mock_run):
        mock_run.return_value = CommandResult(
            args=["lsblk"],
            returncode=0,
            stdout='{"blockdevices": []}',
            stderr="",
        )
        payload = detect_drives()
        self.assertIn("blockdevices", payload)
        self.assertEqual(mock_run.call_args.args[0][:3], ["lsblk", "--bytes", "--json"])

    @patch("modules.drive_detection.run_command", side_effect=CommandRunnerTimeout("x"))
    def test_detect_drives_timeout(self, _mock_run):
        with self.assertRaises(DriveDetectionError):
            detect_drives()

    @patch("builtins.input", return_value="1,2")
    def test_get_user_input_valid_multi_select(self, _mock_input):
        terminal_ui = Mock()
        drives = [
            Drive("a", "/dev/sda", "1T", "", "", "", "disk", [], False, "sata", True),
            Drive("b", "/dev/sdb", "1T", "", "", "", "disk", [], False, "sata", False),
        ]
        selected = get_user_input(drives, terminal_ui)
        self.assertEqual([d.path for d in selected], ["/dev/sda", "/dev/sdb"])

    @patch("builtins.input", side_effect=["f", "11"])
    def test_get_user_input_supports_forward_paging(self, _mock_input):
        terminal_ui = Mock()
        drives = [
            Drive(f"d{idx}", f"/dev/sd{idx}", "1T", "", "", "", "disk", [], False, "sata", True)
            for idx in range(12)
        ]
        selected = get_user_input(drives, terminal_ui)
        self.assertEqual([d.path for d in selected], ["/dev/sd10"])

    @patch("builtins.input", return_value="b")
    def test_get_user_input_supports_back_command(self, _mock_input):
        terminal_ui = Mock()
        drives = [
            Drive("a", "/dev/sda", "1T", "", "", "", "disk", [], False, "sata", True),
        ]
        selected = get_user_input(drives, terminal_ui)
        self.assertEqual(selected, [])

    @patch("builtins.input", side_effect=["y", "wipe"])
    def test_confirm_all_drives_two_steps_success(self, _mock_input):
        cfg = SimpleNamespace(safety=SimpleNamespace(confirmation_steps=2))
        terminal_ui = Mock()
        selected = [Drive("a", "/dev/sda", "1T", "", "", "", "disk", [], False, "sata", True)]
        self.assertTrue(confirm_all_drives(selected, cfg, terminal_ui))


if __name__ == "__main__":
    unittest.main()
