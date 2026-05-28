"""
uploader.py - Git-based report upload with retry and local queue semantics.

Handles upload of wipe reports to a private Git repository with:
- Network failure tolerance (reports retained locally until upload succeeds)
- Exponential backoff retry logic
- Proper state tracking to prevent double-uploads
- Support for offline operation (reports queued locally, uploaded when network available)
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from modules.app_logging import log_error, log_info
from modules.terminal import CommandRunnerError, CommandRunnerTimeout, run_command


class UploadError(Exception):
    """Raised when upload cannot proceed safely."""


@dataclass
class UploadQueue:
    """Tracks pending reports awaiting successful upload."""

    reports_dir: Path
    queue_file: Path

    def __post_init__(self):
        """Ensure queue file and reports directory exist."""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def add_pending(self, report_path: Path) -> None:
        """Mark a report as pending upload by recording its path in queue."""
        if not report_path.exists():
            raise UploadError(f"Report file does not exist: {report_path}")

        pending = self._read_queue()
        report_str = str(report_path.resolve())
        if report_str not in pending:
            pending.append(report_str)
            self._write_queue(pending)
            log_info(f"Added to upload queue: {report_path}")

    def mark_uploaded(self, report_path: Path) -> None:
        """Remove a report from pending queue after successful upload."""
        pending = self._read_queue()
        report_str = str(report_path.resolve())
        if report_str in pending:
            pending.remove(report_str)
            self._write_queue(pending)
            log_info(f"Removed from upload queue: {report_path}")

    def list_pending(self) -> list[Path]:
        """Return list of pending report paths awaiting upload."""
        pending = self._read_queue()
        return [Path(p) for p in pending if Path(p).exists()]

    def _read_queue(self) -> list[str]:
        """Read pending report paths from queue file."""
        if not self.queue_file.exists():
            return []

        try:
            text = self.queue_file.read_text(encoding="utf-8").strip()
            return [line for line in text.split("\n") if line]
        except (OSError, UnicodeDecodeError):
            return []

    def _write_queue(self, pending: list[str]) -> None:
        """Write pending report paths to queue file."""
        self.queue_file.write_text("\n".join(pending) + "\n", encoding="utf-8")


class GitUploader:
    """Handles git operations for report upload."""

    def __init__(
        self,
        repo_url: str,
        repo_path: Path,
        branch: str = "main",
        ssh_private_key_path: Optional[str] = None,
    ):
        """Initialize uploader with target repo and branch."""
        self.repo_url = repo_url
        self.repo_path = repo_path
        self.branch = branch
        self.ssh_private_key_path = ssh_private_key_path.strip() if ssh_private_key_path else None

    def _git_env(self) -> dict[str, str] | None:
        """Build optional environment overrides for git commands."""
        if not self.ssh_private_key_path:
            return None

        key_path = Path(self.ssh_private_key_path).expanduser()
        if not key_path.is_file():
            raise UploadError(f"SSH private key not found: {key_path}")

        return {
            "GIT_SSH_COMMAND": (
                f"ssh -i {key_path} -o IdentitiesOnly=yes "
                "-o StrictHostKeyChecking=accept-new"
            )
        }

    def ensure_repo_initialized(self) -> None:
        """Clone repo if missing, or verify existing clone is valid."""
        if self.repo_path.exists():
            self._verify_repo_valid()
        else:
            self._clone_repo()

    def _clone_repo(self) -> None:
        """Clone the repository from remote URL."""
        self.repo_path.parent.mkdir(parents=True, exist_ok=True)
        git_env = self._git_env()
        try:
            run_command(
                ["git", "clone", "--depth", "1", "--branch", self.branch, self.repo_url, str(self.repo_path)],
                timeout=60,
                check=True,
                env=git_env,
            )
            log_info(f"Cloned repository: {self.repo_url}")
        except (CommandRunnerError, CommandRunnerTimeout) as exc:
            raise UploadError(f"Failed to clone repository: {exc}") from exc

    def _verify_repo_valid(self) -> None:
        """Verify the repo path is a valid git repository."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise UploadError(f"Repository path is not a valid git repository: {self.repo_path}")

    def stage_and_commit(self, report_paths: list[Path], message: str) -> bool:
        """Stage report files and commit to local repo. Returns True on success."""
        if not report_paths:
            return False

        try:
            git_env = self._git_env()

            # Change to repo directory for all git operations
            for report_path in report_paths:
                if not report_path.exists():
                    continue

                # Copy report file into repo, preserving filename
                dest_path = self.repo_path / "reports" / report_path.name
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # Read source and write to destination
                dest_path.write_bytes(report_path.read_bytes())
                log_info(f"Staged report in repo: {dest_path}")

            # Stage all files in reports directory
            run_command(
                ["git", "-C", str(self.repo_path), "add", "reports/"],
                timeout=30,
                check=True,
                env=git_env,
            )

            # Commit with provided message
            run_command(
                ["git", "-C", str(self.repo_path), "commit", "-m", message],
                timeout=30,
                check=False,  # Commit may fail if no changes
                env=git_env,
            )
            log_info(f"Committed reports to local repository")
            return True

        except (CommandRunnerError, CommandRunnerTimeout) as exc:
            log_error(f"Failed to stage/commit reports: {exc}")
            return False

    def push_to_remote(self, max_retries: int = 3) -> bool:
        """Push commits to remote with exponential backoff retry. Returns True on success."""
        try:
            git_env = self._git_env()
        except UploadError as exc:
            log_error(str(exc))
            return False

        for attempt in range(max_retries):
            try:
                # Rebase local commits on the latest remote branch to reduce
                # non-fast-forward push failures when multiple devices upload.
                run_command(
                    ["git", "-C", str(self.repo_path), "pull", "--rebase", "origin", self.branch],
                    timeout=60,
                    check=True,
                    env=git_env,
                )

                run_command(
                    ["git", "-C", str(self.repo_path), "push", "origin", self.branch],
                    timeout=60,
                    check=True,
                    env=git_env,
                )
                log_info(f"Successfully pushed reports to remote branch: {self.branch}")
                return True

            except CommandRunnerTimeout as exc:
                log_error(f"Push attempt {attempt + 1} timed out: {exc}")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    log_info(f"Retrying push in {backoff}s...")
                    time.sleep(backoff)

            except CommandRunnerError as exc:
                # Check if it's a network error (common patterns in git stderr)
                error_msg = str(exc).lower()
                is_network_error = any(
                    keyword in error_msg
                    for keyword in ["network", "unreachable", "connection refused", "temporary failure", "ssh"]
                )

                if is_network_error:
                    log_error(f"Push attempt {attempt + 1} failed (network): {exc}")
                    if attempt < max_retries - 1:
                        backoff = 2 ** attempt
                        log_info(f"Retrying push in {backoff}s...")
                        time.sleep(backoff)
                else:
                    # Non-network error; don't retry
                    log_error(f"Push failed (non-network error): {exc}")
                    return False

        log_error(f"Push failed after {max_retries} attempts")
        return False


def _resolve_upload_paths(app_config: Any) -> tuple[Path, Path, Path]:
    """Resolve reports dir, queue file path, and local upload repo path from config."""
    paths_cfg = getattr(app_config, "paths", object())
    reports_dir = Path(getattr(paths_cfg, "reports_dir", "./reports"))

    state_dir_value = getattr(paths_cfg, "state_dir", None)
    if state_dir_value:
        state_dir = Path(state_dir_value)
    else:
        state_dir = reports_dir.parent / "state"

    queue_file = state_dir / ".upload_queue"
    repo_path = state_dir / ".upload_repo"
    return reports_dir, queue_file, repo_path


def _push_pending_queue(queue: UploadQueue, uploader: GitUploader, max_retries: int) -> bool:
    """Push all queued reports and clear successful entries."""
    pending = queue.list_pending()
    if not pending:
        log_info("No pending reports to upload")
        return True

    try:
        uploader.ensure_repo_initialized()
    except UploadError as exc:
        log_error(f"Failed to initialize repository: {exc}")
        return False

    timestamp = int(time.time())
    commit_message = f"Upload {len(pending)} report(s) [timestamp: {timestamp}]"
    if not uploader.stage_and_commit(pending, commit_message):
        log_error("Failed to stage/commit reports; upload aborted")
        return False

    if uploader.push_to_remote(max_retries=max_retries):
        for report_path in pending:
            queue.mark_uploaded(report_path)
        log_info(f"Successfully uploaded {len(pending)} report(s)")
        return True

    log_error("Failed to push reports; retaining locally for next attempt")
    return False


def flush_pending_reports(app_config: Any, dry_run: bool = False) -> bool:
    """Attempt to upload any reports already present in the local queue."""
    upload_cfg = getattr(app_config, "upload", object())
    if not getattr(upload_cfg, "enabled", False):
        return True

    repo_url = getattr(upload_cfg, "repo", None)
    if not repo_url:
        log_error("Upload is enabled but no repository URL configured")
        return False

    if dry_run:
        log_info(f"[DRY RUN] Would flush queued reports to: {repo_url}")
        return True

    reports_dir, queue_file, repo_path = _resolve_upload_paths(app_config)
    queue = UploadQueue(reports_dir=reports_dir, queue_file=queue_file)
    branch = getattr(upload_cfg, "branch", "main")
    retry_count = int(getattr(upload_cfg, "retry_count", 3))
    ssh_private_key_path = getattr(upload_cfg, "ssh_private_key_path", None)

    try:
        uploader = GitUploader(
            repo_url,
            repo_path,
            branch=branch,
            ssh_private_key_path=ssh_private_key_path,
        )
    except UploadError as exc:
        log_error(f"Failed to initialize uploader: {exc}")
        return False

    return _push_pending_queue(queue, uploader, max_retries=max(1, retry_count))


def upload_reports(
    report_json_path: Path,
    report_text_path: Path,
    app_config: Any,
    dry_run: bool = False,
) -> bool:
    """
    Upload wipe reports to configured Git repository with local queue.

    Args:
        report_json_path: Path to generated JSON report
        report_text_path: Path to generated text report
        app_config: Application configuration object
        dry_run: If True, skip actual upload but log intent

    Returns:
        True if upload succeeded or was skipped (dry run), False if failed.
    """
    # Check if upload is enabled/configured
    upload_cfg = getattr(app_config, "upload", object())
    if not getattr(upload_cfg, "enabled", False):
        log_info("Report upload is disabled; reports retained locally")
        return True

    repo_url = getattr(upload_cfg, "repo", None)
    if not repo_url:
        log_error("Upload is enabled but no repository URL configured")
        return False

    if dry_run:
        log_info(f"[DRY RUN] Would upload reports to: {repo_url}")
        return True

    # Initialize upload queue
    reports_dir, queue_file, repo_path = _resolve_upload_paths(app_config)
    queue = UploadQueue(reports_dir=reports_dir, queue_file=queue_file)

    # Add new reports to queue
    queue.add_pending(report_json_path)
    queue.add_pending(report_text_path)

    # Initialize git uploader
    branch = getattr(upload_cfg, "branch", "main")
    retry_count = int(getattr(upload_cfg, "retry_count", 3))
    ssh_private_key_path = getattr(upload_cfg, "ssh_private_key_path", None)

    try:
        uploader = GitUploader(
            repo_url,
            repo_path,
            branch=branch,
            ssh_private_key_path=ssh_private_key_path,
        )
    except UploadError as exc:
        log_error(f"Failed to initialize uploader: {exc}")
        return False

    return _push_pending_queue(queue, uploader, max_retries=max(1, retry_count))
