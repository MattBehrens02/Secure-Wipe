import tempfile
import textwrap
import unittest
from pathlib import Path

from modules import config


class TestConfig(unittest.TestCase):
    def test_load_config_defaults_when_file_missing(self):
        cfg = config.load_config("/tmp/definitely_missing_config.toml")
        self.assertEqual(cfg.runtime.environment, "dev")
        self.assertTrue(cfg.runtime.dry_run)

    def test_load_config_applies_valid_overrides(self):
        toml_text = textwrap.dedent(
            """
            [runtime]
            environment = "test"
            dry_run = false

            [safety]
            removable_drive_mode = "allow"
            mount_handling_mode = "allow"
            confirmation_steps = 1

            [drive_detection]
            collect_smart_info = false

            [recovery]
            checkpoint_interval_seconds = 30
            max_resume_attempts = 5
            lock_stale_seconds = 3600
            resume_state_max_age_seconds = 43200
            allow_failed_resume = true

            [reporting]
            formats = ["json"]
            detail_level = "standard"

            [logging]
            enabled = true
            level = "errors"
            """
        )

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        cfg = config.load_config(tmp_path)
        self.assertEqual(cfg.runtime.environment, "test")
        self.assertFalse(cfg.runtime.dry_run)
        self.assertEqual(cfg.safety.removable_drive_mode, "allow")
        self.assertEqual(cfg.safety.mount_handling_mode, "allow")
        self.assertEqual(cfg.safety.confirmation_steps, 1)
        self.assertFalse(cfg.drive_detection.collect_smart_info)
        self.assertEqual(cfg.recovery.checkpoint_interval_seconds, 30)
        self.assertEqual(cfg.recovery.max_resume_attempts, 5)
        self.assertEqual(cfg.recovery.lock_stale_seconds, 3600)
        self.assertEqual(cfg.recovery.resume_state_max_age_seconds, 43200)
        self.assertTrue(cfg.recovery.allow_failed_resume)
        self.assertEqual(cfg.reporting.formats, ["json"])
        self.assertEqual(cfg.reporting.detail_level, "standard")
        self.assertTrue(cfg.logging.enabled)
        self.assertEqual(cfg.logging.level, "errors")

    def test_rejects_unknown_toml_table(self):
        toml_text = "[unknown]\nvalue = 1\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        with self.assertRaises(ValueError):
            config.load_config(tmp_path)

    def test_rejects_invalid_environment(self):
        toml_text = "[runtime]\nenvironment = \"staging\"\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        with self.assertRaises(ValueError):
            config.load_config(tmp_path)

    def test_prod_environment_overrides_paths_to_project_root(self):
        toml_text = "[runtime]\nenvironment = \"prod\"\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        cfg = config.load_config(tmp_path)
        project_root = Path(config.__file__).resolve().parent.parent
        self.assertEqual(cfg.paths.project_root, str(project_root))
        self.assertEqual(cfg.paths.logs_dir, str(project_root / "logs"))

    def test_prod_environment_uses_output_root_for_persistent_paths(self):
        with tempfile.TemporaryDirectory() as out:
            toml_text = textwrap.dedent(
                f"""
                [paths]
                output_root = "{out}"

                [runtime]
                environment = "prod"
                """
            )

            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
                tmp.write(toml_text)
                tmp_path = tmp.name

            cfg = config.load_config(tmp_path)
            project_root = Path(config.__file__).resolve().parent.parent

            self.assertEqual(cfg.paths.logs_dir, str(Path(out) / "logs"))
            self.assertEqual(cfg.paths.reports_dir, str(Path(out) / "reports"))
            self.assertEqual(cfg.paths.state_dir, str(Path(out) / "state"))
            self.assertEqual(cfg.paths.temp_dir, str(project_root / "tmp"))
            self.assertEqual(cfg.recovery.lock_file_path, str(Path(out) / "state" / "wipe.lock"))

    def test_save_user_config_roundtrip(self):
        cfg = config.AppConfig()
        cfg.runtime.environment = "test"
        cfg.runtime.dry_run = False
        cfg.drive_detection.collect_smart_info = False
        cfg.reporting.detail_level = "standard"
        cfg.upload.enabled = True
        cfg.logging.level = "errors"

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp_path = tmp.name

        output_path = config.save_user_config(cfg, tmp_path)
        self.assertTrue(Path(output_path).exists())

        loaded = config.load_config(tmp_path)
        self.assertEqual(loaded.runtime.environment, "test")
        self.assertFalse(loaded.runtime.dry_run)
        self.assertFalse(loaded.drive_detection.collect_smart_info)
        self.assertEqual(loaded.reporting.detail_level, "standard")
        self.assertTrue(loaded.upload.enabled)
        self.assertEqual(loaded.logging.level, "errors")


if __name__ == "__main__":
    unittest.main()
