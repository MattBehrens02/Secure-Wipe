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

            [wipe]
            container_scrub_pattern = "nnsa"
            hdd_final_scrub_pattern = "dod"

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
        self.assertEqual(cfg.wipe.container_scrub_pattern, "nnsa")
        self.assertEqual(cfg.wipe.hdd_final_scrub_pattern, "dod")
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

    def test_rejects_unsupported_scrub_pattern(self):
        toml_text = textwrap.dedent(
            """
            [wipe]
            container_scrub_pattern = "totallymadeup"
            """
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        with self.assertRaisesRegex(ValueError, "wipe.container_scrub_pattern must be one of"):
            config.load_config(tmp_path)

    def test_accepts_scrub_supported_pattern_outside_ui_cycle(self):
        toml_text = textwrap.dedent(
            """
            [wipe]
            container_scrub_pattern = "schneier"
            hdd_final_scrub_pattern = 'custom=\\xff\\x00'
            """
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml") as tmp:
            tmp.write(toml_text)
            tmp_path = tmp.name

        cfg = config.load_config(tmp_path)
        self.assertEqual(cfg.wipe.container_scrub_pattern, "schneier")
        self.assertEqual(cfg.wipe.hdd_final_scrub_pattern, "custom=\\xff\\x00")

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

        saved_text = Path(output_path).read_text(encoding="utf-8")
        self.assertIn('environment = "test"  # dev | test | prod', saved_text)
        self.assertIn('confirmation_steps = 2  # 2 (recommended) | 1 | 0; 2 = multi-step confirmation [y]es/[n]o + type "WIPE" to confirm', saved_text)
        self.assertIn('level = "errors"  # info | errors', saved_text)

        loaded = config.load_config(tmp_path)
        self.assertEqual(loaded.runtime.environment, "test")
        self.assertFalse(loaded.runtime.dry_run)
        self.assertFalse(loaded.drive_detection.collect_smart_info)
        self.assertEqual(loaded.reporting.detail_level, "standard")
        self.assertTrue(loaded.upload.enabled)
        self.assertEqual(loaded.logging.level, "errors")

    def test_load_config_prefers_output_root_config_in_prod(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as output_dir:
            local_config_path = Path(root_dir) / "configuration.toml"
            local_config_path.write_text(
                textwrap.dedent(
                    f"""
                    [paths]
                    output_root = "{output_dir}"

                    [runtime]
                    environment = "prod"
                    dry_run = true
                    timezone = "UTC"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            output_config_path = Path(output_dir) / "configuration.toml"
            output_config_path.write_text(
                textwrap.dedent(
                    f"""
                    [paths]
                    output_root = "{output_dir}"

                    [runtime]
                    environment = "prod"
                    dry_run = false
                    timezone = "America/Edmonton"

                    [logging]
                    enabled = true
                    level = "errors"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            original_default = config.DEFAULT_CONFIG_PATH
            try:
                config.DEFAULT_CONFIG_PATH = local_config_path
                cfg = config.load_config()
            finally:
                config.DEFAULT_CONFIG_PATH = original_default

            self.assertFalse(cfg.runtime.dry_run)
            self.assertEqual(cfg.runtime.timezone, "America/Edmonton")
            self.assertEqual(cfg.logging.level, "errors")

    def test_save_user_config_defaults_to_output_root_in_prod(self):
        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as root_dir:
            cfg = config.AppConfig()
            cfg.runtime.environment = "prod"
            cfg.paths.output_root = output_dir
            cfg.runtime.timezone = "America/Edmonton"

            original_default = config.DEFAULT_CONFIG_PATH
            try:
                config.DEFAULT_CONFIG_PATH = Path(root_dir) / "configuration.toml"
                output_path = config.save_user_config(cfg)
            finally:
                config.DEFAULT_CONFIG_PATH = original_default

            self.assertEqual(output_path, Path(output_dir) / "configuration.toml")
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
