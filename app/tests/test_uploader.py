import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from modules.uploader import GitUploader, UploadError, UploadQueue, flush_pending_reports, upload_reports


class TestUploadQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.reports_dir = Path(self.temp_dir) / "reports"
        self.queue_file = Path(self.temp_dir) / "state" / ".upload_queue"
        self.queue = UploadQueue(reports_dir=self.reports_dir, queue_file=self.queue_file)

    def test_add_pending_writes_report_path_to_queue(self):
        report_path = self.reports_dir / "test_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"test": true}')

        self.queue.add_pending(report_path)

        pending = self.queue.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0], report_path.resolve())

    def test_add_pending_raises_when_report_missing(self):
        report_path = self.reports_dir / "missing.json"

        with self.assertRaises(UploadError):
            self.queue.add_pending(report_path)

    def test_mark_uploaded_removes_from_queue(self):
        report_path = self.reports_dir / "test_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"test": true}')
        self.queue.add_pending(report_path)

        self.queue.mark_uploaded(report_path)

        pending = self.queue.list_pending()
        self.assertEqual(len(pending), 0)

    def test_list_pending_filters_missing_files(self):
        report_path = self.reports_dir / "test_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"test": true}')
        self.queue.add_pending(report_path)

        # Delete the file
        report_path.unlink()

        # List should return empty because file no longer exists
        pending = self.queue.list_pending()
        self.assertEqual(len(pending), 0)

    def test_queue_persists_across_instances(self):
        report_path = self.reports_dir / "test_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"test": true}')
        self.queue.add_pending(report_path)

        # Create new queue instance
        queue2 = UploadQueue(reports_dir=self.reports_dir, queue_file=self.queue_file)
        pending = queue2.list_pending()

        self.assertEqual(len(pending), 1)


class TestGitUploader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir) / "repo"
        self.repo_url = "git@github.com:test/repo.git"
        self.uploader = GitUploader(self.repo_url, self.repo_path)

    @patch("modules.uploader.run_command")
    def test_clone_repo_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        self.uploader._clone_repo()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[0], "git")
        self.assertEqual(call_args[1], "clone")
        self.assertIn(self.repo_url, call_args)

    @patch("modules.uploader.run_command")
    def test_clone_repo_failure_raises_upload_error(self, mock_run):
        from modules.terminal import CommandRunnerError
        
        mock_run.side_effect = CommandRunnerError("Network error")

        with self.assertRaises(UploadError):
            self.uploader._clone_repo()

    def test_verify_repo_valid_fails_when_not_git_repo(self):
        self.repo_path.mkdir(parents=True, exist_ok=True)

        with self.assertRaises(UploadError):
            self.uploader._verify_repo_valid()

    def test_verify_repo_valid_succeeds_when_git_repo_exists(self):
        git_dir = self.repo_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        # Should not raise
        self.uploader._verify_repo_valid()

    @patch("modules.uploader.run_command")
    def test_stage_and_commit_copies_reports_and_commits(self, mock_run):
        # Setup repo
        self.repo_path.mkdir(parents=True, exist_ok=True)
        git_dir = self.repo_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        # Create report files
        reports_dir = Path(self.temp_dir) / "reports"
        report_json = reports_dir / "report.json"
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text('{"test": true}')

        # Mock git commands
        mock_run.return_value = MagicMock(returncode=0)

        result = self.uploader.stage_and_commit([report_json], "Test commit")

        self.assertTrue(result)
        # Verify file was copied
        repo_report = self.repo_path / "reports" / "report.json"
        self.assertTrue(repo_report.exists())

    @patch("modules.uploader.run_command")
    def test_push_to_remote_success(self, mock_run):
        self.repo_path.mkdir(parents=True, exist_ok=True)
        git_dir = self.repo_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        mock_run.return_value = MagicMock(returncode=0)

        result = self.uploader.push_to_remote(max_retries=1)

        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_run.call_args_list[1][0][0]
        self.assertEqual(first_cmd[:5], ["git", "-C", str(self.repo_path), "pull", "--rebase"])
        self.assertEqual(second_cmd[:4], ["git", "-C", str(self.repo_path), "push"])

    @patch("modules.uploader.time.sleep")  # Mock sleep to avoid delays
    @patch("modules.uploader.run_command")
    def test_push_to_remote_retries_on_network_error(self, mock_run, mock_sleep):
        self.repo_path.mkdir(parents=True, exist_ok=True)
        git_dir = self.repo_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        # Each attempt runs pull --rebase then push. Simulate first two pushes
        # failing with network errors, then succeeding on third attempt.
        from modules.terminal import CommandRunnerError

        push_attempts = {"count": 0}

        def side_effect(cmd, **_kwargs):
            if "push" in cmd:
                push_attempts["count"] += 1
                if push_attempts["count"] == 1:
                    raise CommandRunnerError("network: Connection refused")
                if push_attempts["count"] == 2:
                    raise CommandRunnerError("network: Temporary failure in name resolution")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        result = self.uploader.push_to_remote(max_retries=3)

        self.assertTrue(result)
        # 3 attempts x (pull + push)
        self.assertEqual(mock_run.call_count, 6)

    @patch("modules.uploader.run_command")
    def test_push_to_remote_fails_on_non_network_error(self, mock_run):
        self.repo_path.mkdir(parents=True, exist_ok=True)
        git_dir = self.repo_path / ".git"
        git_dir.mkdir(parents=True, exist_ok=True)

        from modules.terminal import CommandRunnerError

        mock_run.side_effect = CommandRunnerError("permission denied")

        result = self.uploader.push_to_remote(max_retries=3)

        self.assertFalse(result)
        # Should only attempt once (no retry on non-network error), failing on pull.
        self.assertEqual(mock_run.call_count, 1)


class TestUploadReports(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.reports_dir = Path(self.temp_dir) / "reports"
        self.state_dir = Path(self.temp_dir) / "state"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.report_json = self.reports_dir / "report.json"
        self.report_text = self.reports_dir / "report.txt"
        self.report_json.write_text('{"test": true}')
        self.report_text.write_text("Test report")

    def test_upload_reports_dry_run_returns_true(self):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=True, repo="git@github.com:test/repo.git"),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=True)

        self.assertTrue(result)

    def test_upload_reports_disabled_returns_true(self):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=False),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=False)

        self.assertTrue(result)

    def test_upload_reports_no_repo_url_returns_false(self):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=True, repo=None),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=False)

        self.assertFalse(result)

    @patch("modules.uploader.GitUploader.push_to_remote", return_value=True)
    @patch("modules.uploader.GitUploader.stage_and_commit", return_value=True)
    @patch("modules.uploader.GitUploader.ensure_repo_initialized")
    def test_upload_reports_success_marks_uploaded(self, mock_init, mock_stage, mock_push):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=True, repo="git@github.com:test/repo.git", branch="main"),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=False)

        self.assertTrue(result)
        # Queue should be empty after successful upload
        queue = UploadQueue(reports_dir=self.reports_dir, queue_file=self.state_dir / ".upload_queue")
        pending = queue.list_pending()
        self.assertEqual(len(pending), 0)

    @patch("modules.uploader.GitUploader.push_to_remote", return_value=False)
    @patch("modules.uploader.GitUploader.stage_and_commit", return_value=True)
    @patch("modules.uploader.GitUploader.ensure_repo_initialized")
    def test_upload_reports_failure_keeps_reports_in_queue(self, mock_init, mock_stage, mock_push):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=True, repo="git@github.com:test/repo.git", branch="main"),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=False)

        self.assertFalse(result)
        # Queue should still contain reports after failed upload
        queue = UploadQueue(reports_dir=self.reports_dir, queue_file=self.state_dir / ".upload_queue")
        pending = queue.list_pending()
        self.assertGreater(len(pending), 0)

    @patch("modules.uploader.GitUploader.push_to_remote", return_value=False)
    @patch("modules.uploader.GitUploader.stage_and_commit", return_value=True)
    @patch("modules.uploader.GitUploader.ensure_repo_initialized")
    def test_upload_reports_uses_configured_state_dir_for_queue(self, _mock_init, _mock_stage, _mock_push):
        custom_state_dir = Path(self.temp_dir) / "persistent-state"
        custom_state_dir.mkdir(parents=True, exist_ok=True)

        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=True, repo="git@github.com:test/repo.git", branch="main"),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir), state_dir=str(custom_state_dir)),
        )

        result = upload_reports(self.report_json, self.report_text, app_config, dry_run=False)

        self.assertFalse(result)
        queue = UploadQueue(reports_dir=self.reports_dir, queue_file=custom_state_dir / ".upload_queue")
        self.assertGreater(len(queue.list_pending()), 0)


class TestFlushPendingReports(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.reports_dir = Path(self.temp_dir) / "reports"
        self.state_dir = Path(self.temp_dir) / "state"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.report_json = self.reports_dir / "report.json"
        self.report_text = self.reports_dir / "report.txt"
        self.report_json.write_text('{"test": true}')
        self.report_text.write_text("Test report")

    def test_flush_pending_reports_returns_true_when_disabled(self):
        app_config = SimpleNamespace(
            upload=SimpleNamespace(enabled=False),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir), state_dir=str(self.state_dir)),
        )

        self.assertTrue(flush_pending_reports(app_config, dry_run=False))

    @patch("modules.uploader.GitUploader.push_to_remote", return_value=True)
    @patch("modules.uploader.GitUploader.stage_and_commit", return_value=True)
    @patch("modules.uploader.GitUploader.ensure_repo_initialized")
    def test_flush_pending_reports_uploads_existing_queue(self, _mock_init, _mock_stage, _mock_push):
        queue = UploadQueue(reports_dir=self.reports_dir, queue_file=self.state_dir / ".upload_queue")
        queue.add_pending(self.report_json)
        queue.add_pending(self.report_text)

        app_config = SimpleNamespace(
            upload=SimpleNamespace(
                enabled=True,
                repo="git@github.com:test/repo.git",
                branch="main",
                retry_count=4,
            ),
            paths=SimpleNamespace(reports_dir=str(self.reports_dir), state_dir=str(self.state_dir)),
        )

        result = flush_pending_reports(app_config, dry_run=False)

        self.assertTrue(result)
        self.assertEqual(len(queue.list_pending()), 0)


if __name__ == "__main__":
    unittest.main()
