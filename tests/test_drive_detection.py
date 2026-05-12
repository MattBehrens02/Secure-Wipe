import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from modules import drive_detection


class TestDriveDetection(unittest.TestCase):
    def test_normalize_drive_data_handles_missing_fields(self) -> None:
        raw = {
            "name": "sdb",
            "path": "/dev/sdb",
            "size": "",
            "model": None,
            "vendor": None,
            "serial": None,
            "type": "disk",
            "mountpoints": None,
            "rm": 0,
            "tran": None,
        }

        drive = drive_detection._normalize_drive_data(raw)

        self.assertEqual(drive.name, "sdb")
        self.assertEqual(drive.path, "/dev/sdb")
        self.assertEqual(drive.size, "")
        self.assertEqual(drive.model, "")
        self.assertEqual(drive.vendor, "")
        self.assertEqual(drive.serial, "")
        self.assertEqual(drive.type, "disk")
        self.assertEqual(drive.mountpoints, [])
        self.assertFalse(drive.removable)
        self.assertEqual(drive.transport, "")

    def test_normalize_drive_data_maps_and_sanitizes_fields(self) -> None:
        raw = {
            "name": "sdb",
            "path": "/dev/sdb",
            "size": "931.5G",
            "model": "  Samsung SSD  ",
            "vendor": "  Samsung  ",
            "serial": "ABC123",
            "type": "disk",
            "mountpoints": [None, "/mnt/data"],
            "rm": 1,
            "tran": "usb",
        }

        drive = drive_detection._normalize_drive_data(raw)

        self.assertEqual(drive.name, "sdb")
        self.assertEqual(drive.path, "/dev/sdb")
        self.assertEqual(drive.size, "931.5G")
        self.assertEqual(drive.model, "Samsung SSD")
        self.assertEqual(drive.vendor, "Samsung")
        self.assertEqual(drive.serial, "ABC123")
        self.assertEqual(drive.type, "disk")
        self.assertEqual(drive.mountpoints, ["/mnt/data"])
        self.assertTrue(drive.removable)
        self.assertEqual(drive.transport, "usb")

    @patch("modules.drive_detection.subprocess.run")
    def test_detect_drives_handles_empty_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="{}")

        result = drive_detection.detect_drives()

        self.assertEqual(result, {})
        mock_run.assert_called_once()

    @patch("modules.drive_detection.subprocess.run")
    def test_detect_drives_handles_invalid_json(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="not a json")

        with self.assertRaises(drive_detection.DriveDetectionError) as ctx:
            drive_detection.detect_drives()

        self.assertIn("failed to parse lsblk output", str(ctx.exception))

    @patch("modules.drive_detection._is_mounted")
    def test_is_blocked_by_safety_modes_respects_config(self, mock_is_mounted: MagicMock) -> None:
        mock_is_mounted.return_value = True
        app_config = MagicMock()
        app_config.safety.removable_drive_mode = "deny"
        app_config.safety.mount_handling_mode = "deny"

        drive = drive_detection.Drive(
            name="sda",
            path="/dev/sda",
            size="100G",
            model="Disk A",
            vendor="Vendor A",
            serial="SER-A",
            type="disk",
            mountpoints=["/mnt/data"],
            removable=True,
            transport="usb",
        )

        blocked, reason = drive_detection._is_blocked_by_safety_modes(drive, app_config)
        self.assertTrue(blocked)
        self.assertIn("removable drives are set to deny", reason)

    @patch("modules.drive_detection._is_mounted")
    def test_requires_extra_confirmation_respects_config(self, mock_is_mounted: MagicMock) -> None:
        mock_is_mounted.return_value = True
        app_config = MagicMock()
        app_config.safety.removable_drive_mode = "confirm"
        app_config.safety.mount_handling_mode = "confirm"

        drive = drive_detection.Drive(
            name="sda",
            path="/dev/sda",
            size="100G",
            model="Disk A",
            vendor="Vendor A",
            serial="SER-A",
            type="disk",
            mountpoints=["/mnt/data"],
            removable=True,
            transport="usb",
        )

        result = drive_detection._requires_extra_confirmation(drive, app_config)
        self.assertTrue(result)

    @patch("modules.drive_detection.get_user_input")
    @patch("modules.drive_detection.detect_drives")
    def test_run_handles_no_drives_detected(self, mock_detect_drives: MagicMock, mock_get_user_input: MagicMock) -> None:
        mock_detect_drives.return_value = {"blockdevices": []}
        mock_get_user_input.return_value = []

        result = drive_detection.run()

        self.assertEqual(result, [])
        mock_detect_drives.assert_called_once()
        mock_get_user_input.assert_called_once()

    @patch("modules.drive_detection.subprocess.run")
    def test_detect_drives_returns_parsed_json(self, mock_run: MagicMock) -> None:
        payload = {
            "blockdevices": [
                {"name": "sda", "type": "disk"},
                {"name": "sda1", "type": "part"},
            ]
        }
        mock_run.return_value = MagicMock(stdout=json.dumps(payload))

        result = drive_detection.detect_drives()

        self.assertEqual(result, payload)
        mock_run.assert_called_once_with(
            [
                "lsblk",
                "--json",
                "--output",
                "NAME,PATH,SIZE,MODEL,VENDOR,SERIAL,TYPE,MOUNTPOINTS,RM,TRAN",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

    @patch("modules.drive_detection.subprocess.run")
    def test_detect_drives_timeout_raises_drive_detection_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="lsblk", timeout=10)

        with self.assertRaises(drive_detection.DriveDetectionError) as ctx:
            drive_detection.detect_drives()

        self.assertIn("timed out", str(ctx.exception))

    @patch("modules.drive_detection.print_menu_options")
    @patch("builtins.input", side_effect=["x", "1, 2"])
    def test_get_user_input_retries_then_returns_selected_drives(
        self,
        _mock_input: MagicMock,
        _mock_print_menu: MagicMock,
    ) -> None:
        drives = [
            drive_detection.Drive(
                name="sda",
                path="/dev/sda",
                size="100G",
                model="Disk A",
                vendor="Vendor A",
                serial="SER-A",
                type="disk",
                mountpoints=[],
                removable=False,
                transport="ata",
            ),
            drive_detection.Drive(
                name="sdb",
                path="/dev/sdb",
                size="200G",
                model="Disk B",
                vendor="Vendor B",
                serial="SER-B",
                type="disk",
                mountpoints=[],
                removable=True,
                transport="usb",
            ),
        ]

        result = drive_detection.get_user_input(drives)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].path, "/dev/sda")
        self.assertEqual(result[1].path, "/dev/sdb")

    @patch("modules.drive_detection.get_user_input")
    @patch("modules.drive_detection.detect_drives")
    def test_run_filters_non_disks_before_prompt(
        self,
        mock_detect_drives: MagicMock,
        mock_get_user_input: MagicMock,
    ) -> None:
        mock_detect_drives.return_value = {
            "blockdevices": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "size": "100G",
                    "model": "Disk A",
                    "vendor": "Vendor A",
                    "serial": "SER-A",
                    "type": "disk",
                    "mountpoints": [None],
                    "rm": 0,
                    "tran": "ata",
                },
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "size": "50G",
                    "type": "part",
                    "mountpoints": ["/"],
                    "rm": 0,
                    "tran": "ata",
                },
            ]
        }

        selected = [
            drive_detection.Drive(
                name="sda",
                path="/dev/sda",
                size="100G",
                model="Disk A",
                vendor="Vendor A",
                serial="SER-A",
                type="disk",
                mountpoints=[],
                removable=False,
                transport="ata",
            )
        ]
        mock_get_user_input.return_value = selected

        result = drive_detection.run()

        self.assertEqual(result, selected)
        args, _kwargs = mock_get_user_input.call_args
        self.assertEqual(len(args[0]), 1)
        self.assertEqual(args[0][0].type, "disk")


if __name__ == "__main__":
    unittest.main()
