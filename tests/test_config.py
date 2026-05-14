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

            [reporting]
            reports_enabled = true
            formats = ["json"]
            detail_level = "standard"

            [logging]
            level = "warning"
            console_level = "error"
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
        self.assertEqual(cfg.reporting.formats, ["json"])
        self.assertEqual(cfg.reporting.detail_level, "standard")
        self.assertEqual(cfg.logging.level, "warning")
        self.assertEqual(cfg.logging.console_level, "error")

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


if __name__ == "__main__":
    unittest.main()
