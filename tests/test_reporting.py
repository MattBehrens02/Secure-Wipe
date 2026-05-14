import json
import tempfile
import unittest
from types import SimpleNamespace

from modules import reporting


class TestReporting(unittest.TestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(
            runtime=SimpleNamespace(environment="test", dry_run=True),
            reporting=SimpleNamespace(detail_level="verbose"),
            paths=SimpleNamespace(reports_dir="/tmp"),
        )
        self.drive = SimpleNamespace(
            name="sda",
            path="/dev/sda",
            size="1T",
            media_type="HDD",
            model="Model",
            vendor="Vendor",
            serial="SER",
            type="disk",
            mountpoints=["/mnt"],
            removable=False,
            transport="sata",
            smart_data={"ok": True},
        )

    def test_build_detection_report_verbose(self):
        data = reporting.build_detection_report(self.cfg, [self.drive])
        self.assertEqual(data["selection"]["selected_count"], 1)
        self.assertEqual(data["drives"][0]["path"], "/dev/sda")
        self.assertIn("smart_data", data["drives"][0])

    def test_build_detection_report_minimal(self):
        self.cfg.reporting.detail_level = "minimal"
        data = reporting.build_detection_report(self.cfg, [self.drive])
        self.assertEqual(set(data["drives"][0].keys()), {"path", "size"})

    def test_write_json_report_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = reporting.write_json_report({"x": 1}, tmpdir)
            with open(out, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["x"], 1)


if __name__ == "__main__":
    unittest.main()
