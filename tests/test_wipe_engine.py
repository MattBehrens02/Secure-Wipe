import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.wipe_engine import WipeEngine


class TestWipeEngine(unittest.TestCase):
    def setUp(self):
        self.drive = SimpleNamespace(path="/dev/sdz")

    def test_execute_dry_run_returns_and_skips_steps(self):
        engine = WipeEngine(self.drive, dry_run=True)

        with patch.object(engine, "generate_temporary_key") as gen_key, \
             patch.object(engine, "create_luks2_container") as luks_format, \
             patch.object(engine, "open_encrypted_container") as luks_open, \
             patch.object(engine, "write_across_encrypted_drive") as scrub, \
             patch.object(engine, "close_encrypted_container") as luks_close, \
             patch.object(engine, "destroy_luks2_container") as destroy_header, \
             patch.object(engine, "remove_residual_signatures") as wipefs:
            result = engine.execute()

        self.assertEqual(result.status, "dry_run")
        gen_key.assert_not_called()
        luks_format.assert_not_called()
        luks_open.assert_not_called()
        scrub.assert_not_called()
        luks_close.assert_not_called()
        destroy_header.assert_not_called()
        wipefs.assert_not_called()

    def test_execute_runs_steps_in_order_when_not_dry_run(self):
        engine = WipeEngine(self.drive, dry_run=False)
        calls = []

        with patch.object(engine, "generate_temporary_key", side_effect=lambda: calls.append("generate_temporary_key")), \
             patch.object(engine, "create_luks2_container", side_effect=lambda: calls.append("create_luks2_container")), \
             patch.object(engine, "open_encrypted_container", side_effect=lambda: calls.append("open_encrypted_container")), \
             patch.object(engine, "write_across_encrypted_drive", side_effect=lambda: calls.append("write_across_encrypted_drive")), \
             patch.object(engine, "close_encrypted_container", side_effect=lambda: calls.append("close_encrypted_container")), \
             patch.object(engine, "destroy_luks2_container", side_effect=lambda: calls.append("destroy_luks2_container")), \
             patch.object(engine, "remove_residual_signatures", side_effect=lambda: calls.append("remove_residual_signatures")):
            result = engine.execute()

        self.assertEqual(result.status, "success")
        self.assertEqual(
            calls,
            [
                "generate_temporary_key",
                "create_luks2_container",
                "open_encrypted_container",
                "write_across_encrypted_drive",
                "close_encrypted_container",
                "destroy_luks2_container",
                "remove_residual_signatures",
            ],
        )

    def test_generate_temporary_key_invokes_dd(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.generate_temporary_key()

        mock_run.assert_called_once_with(
            ["dd", "if=/dev/urandom", "of=/tmp/securewipe.key", "bs=1M", "count=4"],
            check=True,
        )

    def test_create_luks2_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.create_luks2_container()

        mock_run.assert_called_once_with(
            [
                "cryptsetup",
                "luksFormat",
                "--type",
                "luks2",
                "--batch-mode",
                "--key-file",
                "/tmp/securewipe.key",
                "/dev/sdz",
            ],
            check=True,
        )

    def test_open_encrypted_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.open_encrypted_container()

        mock_run.assert_called_once_with(
            [
                "cryptsetup",
                "open",
                "--key-file",
                "/tmp/securewipe.key",
                "/dev/sdz",
                "wipe_sdz",
            ],
            check=True,
        )

    def test_write_across_encrypted_drive_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.write_across_encrypted_drive()

        mock_run.assert_called_once_with(
            ["scrub", "-f", "/dev/mapper/wipe_sdz"],
            check=True,
        )

    def test_close_encrypted_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.close_encrypted_container()

        mock_run.assert_called_once_with(
            ["cryptsetup", "close", "wipe_sdz"],
            check=True,
        )

    def test_destroy_luks2_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.destroy_luks2_container()

        mock_run.assert_called_once_with(
            ["cryptsetup", "erase", "/dev/sdz"],
            check=True,
        )

    def test_remove_residual_signatures_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine.remove_residual_signatures()

        mock_run.assert_called_once_with(
            ["wipefs", "--all", "--force", "/dev/sdz"],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()