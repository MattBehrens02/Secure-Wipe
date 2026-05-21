import tempfile
import unittest
import logging
from pathlib import Path
from types import SimpleNamespace

from modules import app_logging


class TestAppLogging(unittest.TestCase):
    def _build_config(self, logs_dir: str, enabled: bool, level: str):
        return SimpleNamespace(
            paths=SimpleNamespace(logs_dir=logs_dir),
            logging=SimpleNamespace(enabled=enabled, level=level),
        )

    def _current_log_file(self, logs_dir: str) -> Path:
        from datetime import datetime, timezone

        day_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Path(logs_dir) / f"{day_stamp}.log"

    def test_info_level_logs_info_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._build_config(tmp, True, "info")
            app_logging.setup_logging(cfg)

            app_logging.log_info("info message")
            app_logging.log_error("error message")

            logfile = self._current_log_file(tmp)
            self.assertTrue(logfile.exists())
            text = logfile.read_text(encoding="utf-8")
            self.assertIn("info message", text)
            self.assertIn("error message", text)

    def test_errors_level_logs_only_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._build_config(tmp, True, "errors")
            app_logging.setup_logging(cfg)

            app_logging.log_info("this should not be recorded")
            app_logging.log_error("this should be recorded")

            logfile = self._current_log_file(tmp)
            self.assertTrue(logfile.exists())
            text = logfile.read_text(encoding="utf-8")
            self.assertNotIn("this should not be recorded", text)
            self.assertIn("this should be recorded", text)

    def test_disabled_logging_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._build_config(tmp, False, "info")
            app_logging.setup_logging(cfg)
            app_logging.log_info("ignored")
            app_logging.log_error("ignored")

            logfile = self._current_log_file(tmp)
            self.assertFalse(logfile.exists())

    def test_setup_logging_closes_existing_handlers(self):
        logger = logging.getLogger(app_logging.LOGGER_NAME)

        class _DummyHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.closed_called = False

            def emit(self, record):
                return None

            def close(self):
                self.closed_called = True
                super().close()

        dummy_handler = _DummyHandler()
        logger.addHandler(dummy_handler)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfg = self._build_config(tmp, True, "info")
                app_logging.setup_logging(cfg)

            self.assertTrue(dummy_handler.closed_called)
            self.assertNotIn(dummy_handler, logger.handlers)
        finally:
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
