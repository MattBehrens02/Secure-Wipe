import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tempfile

from modules.reporting import (
    WipeReport,
    _serialize_wipe_report,
    generate_wipe_report,
    wipe_report_to_json,
    wipe_report_to_text,
    save_wipe_report,
    _humanize_size,
    _format_duration,
    build_detection_report,
	list_saved_reports,
	read_saved_report,
)
from modules.version import AppVersion

VERSION = AppVersion()


class TestWipeReport(unittest.TestCase):
    def test_wipe_report_creation_with_defaults(self):
        report = WipeReport()
        self.assertEqual(report.report_version, "1.0")
        self.assertEqual(report.operator_identifier, "unknown")
        self.assertEqual(report.encryption, "LUKS2")
        self.assertEqual(report.key_size_bits, 256)
        self.assertEqual(report.scrub_pattern, "nnsa")
        self.assertFalse(report.hdd_final_pass)
        self.assertEqual(report.status, "unknown")
        self.assertEqual(report.step_durations, {})

    def test_wipe_report_creation_with_values(self):
        report = WipeReport(
            timestamp_utc="2026-05-15T14:30:00Z",
            operator_identifier="tech_john",
            status="success",
            duration_seconds=1800.5,
        )
        self.assertEqual(report.timestamp_utc, "2026-05-15T14:30:00Z")
        self.assertEqual(report.operator_identifier, "tech_john")
        self.assertEqual(report.status, "success")
        self.assertEqual(report.duration_seconds, 1800.5)


class TestGenerateWipeReport(unittest.TestCase):
    def setUp(self):
        self.drive = Mock()
        self.drive.path = "/dev/sda"
        self.drive.name = "sda"
        self.drive.model = "Samsung SSD 970"
        self.drive.vendor = "Samsung"
        self.drive.serial = "S4FC123456"
        self.drive.size = "1000204886016"
        self.drive.media_type = "SSD"
        self.drive.transport = "nvme"
        self.drive.removable = False
        self.wipe_result = Mock()
        self.wipe_result.status = "success"
        self.wipe_result.started_at = "2026-05-15T14:02:45Z"
        self.wipe_result.finished_at = "2026-05-15T14:32:45Z"
        self.wipe_result.duration_seconds = 1800.342
        self.wipe_result.failed_step = None
        self.wipe_result.error_message = None
        self.wipe_result.step_durations_seconds = {"generate_temporary_key": 0.145}
        self.app_config = Mock()
        self.app_config.runtime = Mock()
        self.app_config.runtime.environment = "production"
        self.app_config.reporting = Mock()
        self.app_config.reporting.operator_identifier = "tech_john_admin"

    def test_generate_wipe_report_success(self):
        report = generate_wipe_report(self.drive, self.wipe_result, self.app_config)
        self.assertEqual(report.drive_path, "/dev/sda")
        self.assertEqual(report.drive_model, "Samsung SSD 970")
        self.assertEqual(report.drive_serial, "S4FC123456")
        self.assertEqual(report.status, "success")
        self.assertFalse(report.hdd_final_pass)

    def test_generate_wipe_report_with_hdd(self):
        self.drive.media_type = "HDD"
        report = generate_wipe_report(self.drive, self.wipe_result, self.app_config)
        self.assertEqual(report.drive_media_type, "HDD")
        self.assertTrue(report.hdd_final_pass)

    def test_generate_wipe_report_failed_wipe(self):
        self.wipe_result.status = "failed"
        self.wipe_result.failed_step = "write_across_encrypted_drive"
        self.wipe_result.error_message = "Device I/O error"
        report = generate_wipe_report(self.drive, self.wipe_result, self.app_config)
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failed_step, "write_across_encrypted_drive")
        self.assertEqual(report.error_message, "Device I/O error")

    def test_generate_wipe_report_with_verification_result(self):
        verification_result = SimpleNamespace(
            status="passed",
            checks_passed=["luks_header_destroyed", "filesystem_signatures_absent"],
            checks_failed=[],
            verification_errors=[],
        )

        report = generate_wipe_report(
            self.drive,
            self.wipe_result,
            self.app_config,
            verification_result=verification_result,
        )

        self.assertEqual(report.verification_status, "passed")
        self.assertEqual(report.verification_checks_passed, ["luks_header_destroyed", "filesystem_signatures_absent"])

    def test_generate_wipe_report_includes_recovery_resume_fields(self):
        self.wipe_result.recovery_resumed = True
        self.wipe_result.recovery_session_id = "sess-123"
        self.wipe_result.recovery_resume_attempts = 2
        self.wipe_result.recovery_state_status = "completed"
        self.wipe_result.recovery_resume_source_status = "interrupted"

        report = generate_wipe_report(self.drive, self.wipe_result, self.app_config)

        self.assertTrue(report.recovery_resumed)
        self.assertEqual(report.recovery_session_id, "sess-123")
        self.assertEqual(report.recovery_resume_attempts, 2)
        self.assertEqual(report.recovery_state_status, "completed")
        self.assertEqual(report.recovery_resume_source_status, "interrupted")


class TestJsonSerialization(unittest.TestCase):
    def setUp(self):
        self.report = WipeReport(
            timestamp_utc="2026-05-15T14:30:00Z",
            operator_identifier="tech_john",
            status="success",
            drive_path="/dev/sda",
            duration_seconds=1800.5,
        )

    def test_wipe_report_to_json_pretty(self):
        json_str = wipe_report_to_json(self.report, pretty=True)
        self.assertIn("{\n", json_str)
        self.assertIn('"report_version": "1.0"', json_str)
        self.assertIn('"status": "success"', json_str)

    def test_wipe_report_to_json_valid_structure(self):
        json_str = wipe_report_to_json(self.report)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["app"]["name"], "Secure Wipe")
        self.assertEqual(parsed["app"]["version"], VERSION.app_version)
        self.assertEqual(parsed["wipe_status"]["status"], "success")
        self.assertEqual(parsed["operator_identifier"], "tech_john")

    def test_wipe_report_to_json_minimal_omits_verbose_fields(self):
        json_str = wipe_report_to_json(self.report, detail_level="minimal")
        parsed = json.loads(json_str)
        self.assertEqual(parsed["report_detail_level"], "minimal")
        self.assertNotIn("wipe_method", parsed)
        self.assertNotIn("platform", parsed["machine"])

    def test_wipe_report_to_json_standard_includes_method_but_not_step_durations(self):
        self.report.platform = "Linux-5.15"
        self.report.drive_serial = "SER123"
        self.report.step_durations = {"write_across_encrypted_drive": 1800.0}
        json_str = wipe_report_to_json(self.report, detail_level="standard")
        parsed = json.loads(json_str)
        self.assertEqual(parsed["report_detail_level"], "standard")
        self.assertIn("wipe_method", parsed)
        self.assertNotIn("step_durations", parsed["wipe_status"])

    def test_wipe_report_to_json_verbose_includes_recovery_state(self):
        self.report.recovery_resumed = True
        self.report.recovery_session_id = "sess-123"
        self.report.recovery_resume_attempts = 1
        self.report.recovery_state_status = "completed"
        self.report.recovery_resume_source_status = "interrupted"

        json_str = wipe_report_to_json(self.report, detail_level="verbose")
        parsed = json.loads(json_str)

        self.assertTrue(parsed["recovery"]["resumed"])
        self.assertEqual(parsed["recovery"]["session_id"], "sess-123")
        self.assertEqual(parsed["recovery"]["resume_attempts"], 1)


class TestTextFormatting(unittest.TestCase):
    def setUp(self):
        self.report = WipeReport(
            timestamp_utc="2026-05-15T14:30:00Z",
            operator_identifier="tech_john",
            hostname="securewipe-01",
            platform="Linux-5.15",
            environment="production",
            drive_path="/dev/sda",
            drive_name="sda",
            drive_model="Samsung SSD 970",
            status="success",
            duration_seconds=1800.5,
            step_durations={"write_across_encrypted_drive": 1800.0},
        )

    def test_wipe_report_to_text_includes_headers(self):
        text = wipe_report_to_text(self.report)
        self.assertIn("SECUREWIPE OPERATION REPORT", text)
        self.assertIn("TIMESTAMP", text)
        self.assertIn("MACHINE INFORMATION", text)
        self.assertIn("DRIVE METADATA", text)
        self.assertIn("WIPE METHOD", text)
        self.assertIn("WIPE RESULTS", text)

    def test_wipe_report_to_text_success_formatting(self):
        text = wipe_report_to_text(self.report)
        self.assertIn(f"Secure Wipe v{VERSION.app_version}", text)
        self.assertIn("✓ SUCCESS", text)

    def test_wipe_report_to_text_minimal_omits_verbose_sections(self):
        text = wipe_report_to_text(self.report, detail_level="minimal")
        self.assertNotIn("WIPE METHOD", text)
        self.assertNotIn("STEP TIMELINE", text)
        self.assertNotIn("Platform:", text)

    def test_wipe_report_to_text_standard_includes_method_without_timeline(self):
        text = wipe_report_to_text(self.report, detail_level="standard")
        self.assertIn("WIPE METHOD", text)
        self.assertNotIn("STEP TIMELINE", text)

    def test_wipe_report_to_text_failed_formatting(self):
        self.report.status = "failed"
        self.report.failed_step = "write_across_encrypted_drive"
        self.report.error_message = "Device I/O error"
        text = wipe_report_to_text(self.report)
        self.assertIn("✗ FAILED", text)
        self.assertIn("FAILURE DETAILS", text)


class TestUtilityFunctions(unittest.TestCase):
    def test_humanize_size_bytes(self):
        self.assertIn("B", _humanize_size("512"))

    def test_humanize_size_gigabytes(self):
        result = _humanize_size("1099511627776")
        self.assertIn("TB", result)

    def test_format_duration_seconds(self):
        result = _format_duration(30.5)
        self.assertIn("30.50s", result)

    def test_format_duration_minutes(self):
        result = _format_duration(90.5)
        self.assertIn("1m", result)


class TestSaveWipeReport(unittest.TestCase):
    def setUp(self):
        self.report = WipeReport(
            timestamp_utc="2026-05-15T14:30:00Z",
            operator_identifier="tech_john",
            status="success",
            drive_path="/dev/sda",
            drive_serial="S4FC123456",
        )
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_save_wipe_report_creates_directory(self):
        reports_dir = Path(self.temp_dir) / "nonexistent"
        self.assertFalse(reports_dir.exists())
        save_wipe_report(self.report, reports_dir)
        self.assertTrue(reports_dir.exists())

    def test_save_wipe_report_creates_json_file(self):
        json_path, text_path = save_wipe_report(self.report, self.temp_dir)
        self.assertTrue(json_path.exists())
        self.assertTrue(json_path.suffix == ".json")

    def test_save_wipe_report_creates_text_file(self):
        json_path, text_path = save_wipe_report(self.report, self.temp_dir)
        self.assertTrue(text_path.exists())
        self.assertTrue(text_path.suffix == ".txt")

    def test_save_wipe_report_json_content_valid(self):
        json_path, text_path = save_wipe_report(self.report, self.temp_dir)
        content = json_path.read_text()
        parsed = json.loads(content)
        self.assertEqual(parsed["wipe_status"]["status"], "success")
        self.assertEqual(parsed["operator_identifier"], "tech_john")

    def test_save_wipe_report_respects_minimal_detail_level(self):
        json_path, text_path = save_wipe_report(self.report, self.temp_dir, detail_level="minimal")
        parsed = json.loads(json_path.read_text())
        text = text_path.read_text()
        self.assertEqual(parsed["report_detail_level"], "minimal")
        self.assertNotIn("wipe_method", parsed)
        self.assertNotIn("WIPE METHOD", text)


class TestDetectionReporting(unittest.TestCase):
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
        data = build_detection_report(self.cfg, [self.drive])
        self.assertEqual(data["selection"]["selected_count"], 1)
        self.assertEqual(data["drives"][0]["path"], "/dev/sda")
        self.assertIn("smart_data", data["drives"][0])

    def test_build_detection_report_minimal(self):
        self.cfg.reporting.detail_level = "minimal"
        data = build_detection_report(self.cfg, [self.drive])
        self.assertEqual(set(data["drives"][0].keys()), {"path", "size"})


class TestSavedReportUtilities(unittest.TestCase):
    def test_list_saved_reports_returns_newest_first_and_filters_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            older_txt = reports_dir / "older.txt"
            newer_json = reports_dir / "newer.json"
            ignored_file = reports_dir / "notes.log"

            older_txt.write_text("old", encoding="utf-8")
            ignored_file.write_text("ignore", encoding="utf-8")
            newer_json.write_text("{}", encoding="utf-8")

            reports = list_saved_reports(reports_dir)
            self.assertEqual([path.name for path in reports], ["newer.json", "older.txt"])

    def test_list_saved_reports_returns_empty_when_directory_missing(self):
        reports = list_saved_reports("/tmp/definitely_missing_securewipe_reports")
        self.assertEqual(reports, [])

    def test_read_saved_report_reads_utf8_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.txt"
            report_path.write_text("hello world", encoding="utf-8")
            self.assertEqual(read_saved_report(report_path), "hello world")


if __name__ == "__main__":
    unittest.main()
