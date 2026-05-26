import io
import unittest
from contextlib import redirect_stdout

from modules import menu_shell, reporting, version


class TestBranding(unittest.TestCase):
	def test_app_version_uses_secure_wipe_display_name(self):
		self.assertEqual(version.AppVersion.app_name, "Secure-Wipe")

	def test_menu_header_uses_secure_wipe_console_title(self):
		buf = io.StringIO()
		with redirect_stdout(buf):
			menu_shell.header(88)

		self.assertIn("Secure-Wipe Operations Console", buf.getvalue())

	def test_text_report_uses_secure_wipe_header(self):
		report = reporting.WipeReport(
			timestamp_utc="2026-05-26T00:00:00Z",
			operator_identifier="operator-1",
			hostname="secure-wipe",
			platform="Linux",
			environment="test",
			drive_path="/dev/sda",
			drive_name="sda",
			drive_model="Model",
			drive_vendor="Vendor",
			drive_serial="Serial",
			drive_size_human="1.0 TB",
			drive_media_type="SSD",
		)

		text = reporting.wipe_report_to_text(report)

		self.assertIn("SECURE-WIPE OPERATION REPORT", text)
		self.assertIn("Secure-Wipe v26.1.2", text)


if __name__ == "__main__":
	unittest.main()