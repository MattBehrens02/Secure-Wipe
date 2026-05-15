import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.wipe_engine import WipeEngine


class TestWipeEngine(unittest.TestCase):
    def setUp(self):
        self.drive = SimpleNamespace(path="/dev/sdz")

    def test_execute_dry_run_returns_and_runs_internal_steps(self):
        engine = WipeEngine(self.drive, dry_run=True)

        with patch.object(engine, "_generate_temporary_key") as gen_key, \
             patch.object(engine, "_create_luks2_container") as luks_format, \
             patch.object(engine, "_open_encrypted_container") as luks_open, \
             patch.object(engine, "_write_across_encrypted_drive") as scrub, \
             patch.object(engine, "_close_encrypted_container") as luks_close, \
             patch.object(engine, "_destroy_luks2_container") as destroy_header, \
             patch.object(engine, "_remove_residual_signatures") as wipefs:
            result = engine.execute()

        self.assertEqual(result.status, "dry_run")
        gen_key.assert_called_once()
        luks_format.assert_called_once()
        luks_open.assert_called_once()
        scrub.assert_called_once()
        luks_close.assert_called_once()
        destroy_header.assert_called_once()
        wipefs.assert_called_once()

    def test_execute_runs_steps_in_order_when_not_dry_run(self):
        engine = WipeEngine(self.drive, dry_run=False)
        calls = []

        with patch.object(engine, "_generate_temporary_key", side_effect=lambda: calls.append("_generate_temporary_key")), \
             patch.object(engine, "_create_luks2_container", side_effect=lambda: calls.append("_create_luks2_container")), \
             patch.object(engine, "_open_encrypted_container", side_effect=lambda: calls.append("_open_encrypted_container")), \
             patch.object(engine, "_write_across_encrypted_drive", side_effect=lambda: calls.append("_write_across_encrypted_drive")), \
             patch.object(engine, "_close_encrypted_container", side_effect=lambda: calls.append("_close_encrypted_container")), \
             patch.object(engine, "_destroy_luks2_container", side_effect=lambda: calls.append("_destroy_luks2_container")), \
             patch.object(engine, "_remove_residual_signatures", side_effect=lambda: calls.append("_remove_residual_signatures")):
            result = engine.execute()

        self.assertEqual(result.status, "success")
        self.assertEqual(
            calls,
            [
                "_generate_temporary_key",
                "_create_luks2_container",
                "_open_encrypted_container",
                "_write_across_encrypted_drive",
                "_close_encrypted_container",
                "_destroy_luks2_container",
                "_remove_residual_signatures",
            ],
        )

    def test_generate_temporary_key_invokes_dd(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._generate_temporary_key()

        mock_run.assert_called_once_with(
            ["dd", "if=/dev/urandom", "of=/tmp/securewipe.key", "bs=1M", "count=4"],
            check=True,
        )

    def test_create_luks2_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._create_luks2_container()

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
            engine._open_encrypted_container()

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
            engine._write_across_encrypted_drive()

        mock_run.assert_called_once_with(
            ["scrub", "-f", "-p", "nnsa", "/dev/mapper/wipe_sdz"],
            check=True,
        )

    def test_close_encrypted_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._close_encrypted_container()

        mock_run.assert_called_once_with(
            ["cryptsetup", "close", "wipe_sdz"],
            check=True,
        )

    def test_destroy_luks2_container_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._destroy_luks2_container()

        mock_run.assert_called_once_with(
            ["cryptsetup", "erase", "/dev/sdz"],
            check=True,
        )

    def test_remove_residual_signatures_invokes_expected_command(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._remove_residual_signatures()

        mock_run.assert_called_once_with(
            ["wipefs", "--all", "--force", "/dev/sdz"],
            check=True,
        )

    def test_internal_run_step_command_skips_execution_in_dry_run(self):
        engine = WipeEngine(self.drive, dry_run=True)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._run_step_command(["echo", "noop"], "[INFO] test")

        mock_run.assert_not_called()

    def test_execute_runs_final_hdd_overwrite_when_drive_is_hdd(self):
        hdd_drive = SimpleNamespace(path="/dev/sdz", is_hdd=True)
        engine = WipeEngine(hdd_drive, dry_run=False)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive"), \
             patch.object(engine, "_close_encrypted_container"), \
             patch.object(engine, "_destroy_luks2_container"), \
             patch.object(engine, "_remove_residual_signatures"), \
             patch.object(engine, "_final_hdd_overwrite") as final_hdd:
            engine.execute()

        final_hdd.assert_called_once()

    def test_execute_skips_final_hdd_overwrite_when_drive_is_not_hdd(self):
        ssd_drive = SimpleNamespace(path="/dev/sdz", is_hdd=False)
        engine = WipeEngine(ssd_drive, dry_run=False)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive"), \
             patch.object(engine, "_close_encrypted_container"), \
             patch.object(engine, "_destroy_luks2_container"), \
             patch.object(engine, "_remove_residual_signatures"), \
             patch.object(engine, "_final_hdd_overwrite") as final_hdd:
            engine.execute()

        final_hdd.assert_not_called()

    def test_final_hdd_overwrite_invokes_expected_command(self):
        hdd_drive = SimpleNamespace(path="/dev/sdz", is_hdd=True)
        engine = WipeEngine(hdd_drive, dry_run=False)

        with patch("modules.wipe_engine.run_command") as mock_run:
            engine._final_hdd_overwrite()

        mock_run.assert_called_once_with(
            ["scrub", "-f", "-p", "fillzero", "/dev/sdz"],
            check=True,
        )

    def test_execute_returns_structured_failure_result_when_step_raises(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container", side_effect=RuntimeError("boom")), \
             patch.object(engine, "_delete_temporary_key") as cleanup_key:
            result = engine.execute()

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failed_step, "create_luks2_container")
        self.assertIn("boom", result.error_message)
        self.assertEqual(result.drive_path, "/dev/sdz")
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        cleanup_key.assert_called_once()

    def test_execute_attempts_mapper_close_in_finally_when_failure_occurs_after_open(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive", side_effect=RuntimeError("write failed")), \
             patch.object(engine, "_close_encrypted_container") as close_mapper, \
             patch.object(engine, "_delete_temporary_key"):
            result = engine.execute()

        self.assertEqual(result.status, "failed")
        close_mapper.assert_called_once()

    def test_execute_includes_duration_metrics_in_result(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive"), \
             patch.object(engine, "_close_encrypted_container"), \
             patch.object(engine, "_destroy_luks2_container"), \
             patch.object(engine, "_remove_residual_signatures"):
            result = engine.execute()

        self.assertIsNotNone(result.duration_seconds)
        self.assertGreater(result.duration_seconds, 0)
        self.assertIsInstance(result.step_durations_seconds, dict)
        self.assertGreater(len(result.step_durations_seconds), 0)

    def test_execute_carries_pre_wipe_smart_snapshot(self):
        drive = SimpleNamespace(path="/dev/sdz", smart_data={"device": {"name": "sdz"}})
        engine = WipeEngine(drive, dry_run=True)

        with patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive"), \
             patch.object(engine, "_close_encrypted_container"), \
             patch.object(engine, "_destroy_luks2_container"), \
             patch.object(engine, "_remove_residual_signatures"):
            result = engine.execute()

        self.assertEqual(result.smart_before, {"device": {"name": "sdz"}})

    def test_verify_with_config_delegates_to_verification_module(self):
        engine = WipeEngine(self.drive, dry_run=False)

        with patch("modules.verification.verify_wipe", return_value=SimpleNamespace(status="passed")) as mock_verify:
            result = engine.verify_with_config(SimpleNamespace(verification=SimpleNamespace(enabled=True)))

        self.assertEqual(result.status, "passed")
        mock_verify.assert_called_once()

    def test_wipe_result_format_duration_summary_with_human_readable_names(self):
        from modules.wipe_engine import WipeResult
        
        result = WipeResult(
            status="success",
            duration_seconds=10.5,
            step_durations_seconds={
                "generate_temporary_key": 0.1,
                "create_luks2_container": 1.2,
                "write_across_encrypted_drive": 8.5,
            },
        )

        summary = result.format_duration_summary()
        self.assertIn("Duration summary: 10.5s total", summary)
        self.assertIn("Generate Temporary Key: 0.1s", summary)
        self.assertIn("Create Luks2 Container: 1.2s", summary)
        self.assertIn("Write Across Encrypted Drive: 8.5s", summary)

    def test_execute_with_recovery_creates_and_clears_state_on_success(self):
        engine = WipeEngine(self.drive, dry_run=True)
        cfg = SimpleNamespace(
            paths=SimpleNamespace(state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
                max_resume_attempts=3,
            ),
        )

        with patch("modules.wipe_engine.recovery.load_state", return_value=None), \
             patch("modules.wipe_engine.recovery.save_state") as save_state, \
             patch("modules.wipe_engine.recovery.clear_state") as clear_state, \
             patch.object(engine, "_generate_temporary_key"), \
             patch.object(engine, "_create_luks2_container"), \
             patch.object(engine, "_open_encrypted_container"), \
             patch.object(engine, "_write_across_encrypted_drive"), \
             patch.object(engine, "_close_encrypted_container"), \
             patch.object(engine, "_destroy_luks2_container"), \
             patch.object(engine, "_remove_residual_signatures"):
            result = engine.execute_with_recovery(cfg)

        self.assertEqual(result.status, "dry_run")
        self.assertFalse(result.recovery_resumed)
        self.assertGreaterEqual(save_state.call_count, 2)
        clear_state.assert_called_once_with("/tmp/state", "/dev/sdz")

    def test_execute_with_recovery_resumes_after_last_completed_step(self):
        engine = WipeEngine(self.drive, dry_run=False)
        cfg = SimpleNamespace(
            paths=SimpleNamespace(state_dir="/tmp/state"),
            recovery=SimpleNamespace(
                resume_state_max_age_seconds=86400,
                allow_failed_resume=False,
                max_resume_attempts=3,
            ),
        )
        state = SimpleNamespace(
            step_history=["done:generate_temporary_key", "done:create_luks2_container"],
            resume_attempts=0,
            max_resume_attempts=3,
            status="interrupted",
            increment_resume_attempts=Mock(),
            mark_step_started=Mock(),
            mark_step_completed=Mock(),
            mark_completed=Mock(),
            mark_interrupted=Mock(),
            mark_failed=Mock(),
        )
        calls = []

        with patch("modules.wipe_engine.recovery.load_state", return_value=state), \
             patch("modules.wipe_engine.recovery.should_offer_resume", return_value=True), \
             patch("modules.wipe_engine.recovery.save_state"), \
             patch("modules.wipe_engine.recovery.clear_state"), \
             patch.object(engine, "_generate_temporary_key", side_effect=lambda: calls.append("_generate_temporary_key")), \
             patch.object(engine, "_create_luks2_container", side_effect=lambda: calls.append("_create_luks2_container")), \
             patch.object(engine, "_open_encrypted_container", side_effect=lambda: calls.append("_open_encrypted_container")), \
             patch.object(engine, "_write_across_encrypted_drive", side_effect=lambda: calls.append("_write_across_encrypted_drive")), \
             patch.object(engine, "_close_encrypted_container", side_effect=lambda: calls.append("_close_encrypted_container")), \
             patch.object(engine, "_destroy_luks2_container", side_effect=lambda: calls.append("_destroy_luks2_container")), \
             patch.object(engine, "_remove_residual_signatures", side_effect=lambda: calls.append("_remove_residual_signatures")):
            result = engine.execute_with_recovery(cfg)

        self.assertEqual(result.status, "success")
        self.assertTrue(result.recovery_resumed)
        self.assertEqual(result.recovery_resume_source_status, "interrupted")
        self.assertEqual(
            calls,
            [
                "_open_encrypted_container",
                "_write_across_encrypted_drive",
                "_close_encrypted_container",
                "_destroy_luks2_container",
                "_remove_residual_signatures",
            ],
        )
        state.increment_resume_attempts.assert_called_once()


if __name__ == "__main__":
    unittest.main()