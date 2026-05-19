import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.recovery import (
    RecoveryState,
    acquire_lock,
    clear_state,
    list_incomplete_states,
    load_state,
    release_lock,
    save_state,
    should_offer_resume,
)


class TestRecoveryStatePersistence(unittest.TestCase):
    def test_save_and_load_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = RecoveryState(
                session_id="sess-1",
                drive_path="/dev/sdz",
                current_step="open_encrypted_container",
                status="in_progress",
            )
            state.mark_step_started("open_encrypted_container")

            output_path = save_state(tmp, state)
            loaded = load_state(tmp, "/dev/sdz")

            self.assertTrue(output_path.exists())
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.drive_path, "/dev/sdz")
            self.assertEqual(loaded.current_step, "open_encrypted_container")
            self.assertIn("start:open_encrypted_container", loaded.step_history)

    def test_load_state_returns_none_for_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            corrupt_path = Path(tmp) / "dev_sdz.state.json"
            corrupt_path.write_text("{not json}", encoding="utf-8")

            loaded = load_state(tmp, "/dev/sdz")
            self.assertIsNone(loaded)

    def test_list_incomplete_states_filters_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            interrupted = RecoveryState(drive_path="/dev/sda", status="interrupted")
            completed = RecoveryState(drive_path="/dev/sdb", status="completed")
            failed = RecoveryState(drive_path="/dev/sdc", status="failed")

            save_state(tmp, interrupted)
            save_state(tmp, completed)
            save_state(tmp, failed)

            incomplete = list_incomplete_states(tmp)
            paths = {state.drive_path for state in incomplete}

            self.assertIn("/dev/sda", paths)
            self.assertIn("/dev/sdc", paths)
            self.assertNotIn("/dev/sdb", paths)

    def test_clear_state_deletes_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = RecoveryState(drive_path="/dev/sdz")
            save_state(tmp, state)

            deleted = clear_state(tmp, "/dev/sdz")
            loaded = load_state(tmp, "/dev/sdz")

            self.assertTrue(deleted)
            self.assertIsNone(loaded)

    def test_save_and_load_state_prefers_serial_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = RecoveryState(
                session_id="sess-serial",
                drive_path="/dev/sdz",
                status="interrupted",
                metadata={"drive_serial": "SN-ABC-123"},
            )
            output_path = save_state(tmp, state)
            loaded = load_state(tmp, "/dev/renamed", drive_serial="SN-ABC-123")

            self.assertIn("serial_SN-ABC-123.state.json", str(output_path))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.session_id, "sess-serial")

    def test_load_state_with_serial_falls_back_to_path_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = RecoveryState(session_id="sess-path", drive_path="/dev/sdz", status="interrupted")
            save_state(tmp, state)

            loaded = load_state(tmp, "/dev/sdz", drive_serial="SN-NOT-PRESENT")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.session_id, "sess-path")


class TestRecoveryPolicy(unittest.TestCase):
    def test_should_offer_resume_default_policy_blocks_failed(self):
        state = RecoveryState(drive_path="/dev/sdz", status="failed")
        self.assertFalse(should_offer_resume(state))

    def test_should_offer_resume_allows_failed_when_enabled(self):
        state = RecoveryState(drive_path="/dev/sdz", status="failed")
        self.assertTrue(should_offer_resume(state, allow_failed_resume=True))

    def test_should_offer_resume_blocks_old_state(self):
        state = RecoveryState(drive_path="/dev/sdz", status="interrupted")
        old = datetime.now(timezone.utc) - timedelta(days=2)
        state.updated_at = old.isoformat()

        self.assertFalse(should_offer_resume(state, max_age_seconds=86400))

    def test_should_offer_resume_blocks_when_resume_limit_reached(self):
        state = RecoveryState(
            drive_path="/dev/sdz",
            status="interrupted",
            resume_attempts=3,
            max_resume_attempts=3,
        )
        self.assertFalse(should_offer_resume(state))


class TestRecoveryLocking(unittest.TestCase):
    def test_acquire_and_release_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "wipe.lock"
            acquired, error = acquire_lock(lock_path)
            self.assertTrue(acquired)
            self.assertIsNone(error)
            self.assertTrue(lock_path.exists())

            release_lock(lock_path)
            self.assertFalse(lock_path.exists())

    def test_lock_rejects_second_active_acquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "wipe.lock"
            first, _ = acquire_lock(lock_path)
            second, error = acquire_lock(lock_path, stale_after_seconds=3600)

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertIn("Lock file exists", error)

    def test_stale_lock_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "wipe.lock"
            stale_payload = {
                "pid": 1,
                "hostname": "host",
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
                "app_name": "Secure Wipe",
                "app_version": "0.1.0",
            }
            lock_path.write_text(json.dumps(stale_payload), encoding="utf-8")

            acquired, error = acquire_lock(lock_path, stale_after_seconds=1800)

            self.assertTrue(acquired)
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
