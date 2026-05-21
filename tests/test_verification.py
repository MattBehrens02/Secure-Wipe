import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.terminal import CommandResult
from modules.verification import (
    VerificationResult,
    check_filesystem_signatures_absent,
    check_luks_header_destroyed,
    check_random_sector_sampling,
    verify_wipe,
)


class TestVerificationChecks(unittest.TestCase):
    def test_check_luks_header_destroyed_passes_when_luksdump_fails(self):
        with patch("modules.verification.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                args=["cryptsetup", "luksDump", "/dev/sdz"],
                returncode=1,
                stdout="",
                stderr="Device /dev/sdz is not a valid LUKS device.",
            )

            passed, details = check_luks_header_destroyed("/dev/sdz")

        self.assertTrue(passed)
        self.assertEqual(details["returncode"], 1)

    def test_check_luks_header_destroyed_fails_when_header_still_exists(self):
        with patch("modules.verification.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                args=["cryptsetup", "luksDump", "/dev/sdz"],
                returncode=0,
                stdout="LUKS header information",
                stderr="",
            )

            passed, details = check_luks_header_destroyed("/dev/sdz")

        self.assertFalse(passed)
        self.assertIn("LUKS header information", details["stdout"])

    def test_check_filesystem_signatures_absent_passes_when_output_empty(self):
        with patch("modules.verification.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                args=["wipefs", "--list", "/dev/sdz"],
                returncode=0,
                stdout="",
                stderr="",
            )

            passed, details = check_filesystem_signatures_absent("/dev/sdz")

        self.assertTrue(passed)
        self.assertEqual(details["signatures_output"], "")

    def test_check_filesystem_signatures_absent_fails_when_output_present(self):
        with patch("modules.verification.run_command") as mock_run:
            mock_run.return_value = CommandResult(
                args=["wipefs", "--list", "/dev/sdz"],
                returncode=0,
                stdout="0x438 ext4 [filesystem]",
                stderr="",
            )

            passed, details = check_filesystem_signatures_absent("/dev/sdz")

        self.assertFalse(passed)
        self.assertIn("ext4", details["signatures_output"])

    def test_check_random_sector_sampling_hdd_requires_zeroes(self):
        with tempfile.NamedTemporaryFile(delete=False) as device_file:
            device_file.write(b"\x00" * 8192)
            device_path = device_file.name

        self.addCleanup(lambda: os.remove(device_path) if os.path.exists(device_path) else None)
        drive = SimpleNamespace(path=device_path, size="8192", is_hdd=True)

        passed, details = check_random_sector_sampling(drive, sample_ratio=1.0, block_size=4096)

        self.assertTrue(passed)
        self.assertTrue(details["all_samples_zero"])
        self.assertEqual(details["expectation"], "zeroed")

    def test_check_random_sector_sampling_ssd_is_informational(self):
        with tempfile.NamedTemporaryFile(delete=False) as device_file:
            device_file.write(b"A" * 8192)
            device_path = device_file.name

        self.addCleanup(lambda: os.remove(device_path) if os.path.exists(device_path) else None)
        drive = SimpleNamespace(path=device_path, size="8192", media_type="SSD")

        passed, details = check_random_sector_sampling(drive, sample_ratio=1.0, block_size=4096)

        self.assertTrue(passed)
        self.assertFalse(details["all_samples_zero"])
        self.assertEqual(details["expectation"], "informational")


class TestVerifyWipe(unittest.TestCase):
    def setUp(self):
        self.drive = SimpleNamespace(path="/dev/sdz", size="8192", is_hdd=True)
        self.app_config = SimpleNamespace(
            verification=SimpleNamespace(enabled=True, sample_ratio=0.05, smart_checks_enabled=True)
        )

    def test_verify_wipe_returns_failed_when_core_check_fails(self):
        with patch("modules.verification.check_luks_header_destroyed", return_value=(False, {"returncode": 0})), \
             patch("modules.verification.check_filesystem_signatures_absent", return_value=(True, {})), \
             patch("modules.verification.check_random_sector_sampling", return_value=(True, {})), \
             patch("modules.verification.is_smartctl_available", return_value=False):
            result = verify_wipe(self.drive, self.app_config)

        self.assertEqual(result.status, "failed")
        self.assertIn("luks_header_destroyed", result.checks_failed)

    def test_verify_wipe_returns_passed_when_all_core_checks_pass(self):
        with patch("modules.verification.check_luks_header_destroyed", return_value=(True, {})), \
             patch("modules.verification.check_filesystem_signatures_absent", return_value=(True, {})), \
             patch("modules.verification.check_random_sector_sampling", return_value=(True, {})), \
             patch("modules.verification.is_smartctl_available", return_value=False):
            result = verify_wipe(self.drive, self.app_config)

        self.assertEqual(result.status, "passed")
        self.assertEqual(len(result.checks_failed), 0)
        self.assertIn("random_sector_sampling", result.checks_passed)

    def test_verify_wipe_collects_smart_after_when_available(self):
        smart_before = {"device": {"name": "sdz"}}
        smart_after = {"device": {"name": "sdz"}, "temperature": {"current": 30}}

        with patch("modules.verification.check_luks_header_destroyed", return_value=(True, {})), \
             patch("modules.verification.check_filesystem_signatures_absent", return_value=(True, {})), \
             patch("modules.verification.check_random_sector_sampling", return_value=(True, {})), \
             patch("modules.verification.is_smartctl_available", return_value=True), \
             patch("modules.verification.collect_smart_info", return_value=smart_after):
            result = verify_wipe(self.drive, self.app_config, smart_before=smart_before)

        self.assertEqual(result.smart_before, smart_before)
        self.assertEqual(result.smart_after, smart_after)

    def test_verify_wipe_returns_dry_run_when_requested(self):
        with patch("modules.verification.check_luks_header_destroyed", return_value=(True, {"mode": "dry_run"})), \
             patch("modules.verification.check_filesystem_signatures_absent", return_value=(True, {"mode": "dry_run"})), \
             patch("modules.verification.check_random_sector_sampling", return_value=(True, {"mode": "dry_run"})), \
             patch("modules.verification.is_smartctl_available", return_value=False):
            result = verify_wipe(self.drive, self.app_config, dry_run=True)

        self.assertEqual(result.status, "dry_run")

    def test_verify_wipe_not_run_when_disabled(self):
        self.app_config.verification.enabled = False

        result = verify_wipe(self.drive, self.app_config)

        self.assertEqual(result.status, "not_run")
        self.assertIn("verification disabled by configuration", result.verification_errors)


if __name__ == "__main__":
    unittest.main()