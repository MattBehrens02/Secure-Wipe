import subprocess
from dataclasses import dataclass
from typing import Any


class CommandRunnerError(Exception):
    """Raised when an external command cannot be executed successfully."""


class CommandRunnerTimeout(CommandRunnerError):
    """Raised when an external command times out."""


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def run_command(args: list[str], timeout: int | None = None, check: bool = False) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandRunnerTimeout(f"command timed out: {' '.join(args)}") from exc
    except OSError as exc:
        raise CommandRunnerError(f"failed to execute {' '.join(args)}: {exc}") from exc

    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        message = f"command failed with exit code {completed.returncode}: {' '.join(args)}"
        if stderr:
            message = f"{message}: {stderr}"
        raise CommandRunnerError(message)

    return CommandResult(
        args=list(args),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=(completed.stderr or "").strip(),
    )


@dataclass(frozen=True)
class TerminalUI:
    interactive: bool = True

    @classmethod
    def from_config(cls, app_config: Any) -> "TerminalUI":
        environment = getattr(getattr(app_config, "runtime", object()), "environment", "dev")
        return cls(interactive=environment != "dev")

    def clear(self) -> None:
        if not self.interactive:
            return
        subprocess.run(["clear"], check=False)

    def enter_alt_screen(self) -> None:
        if not self.interactive:
            return
        subprocess.run(["tput", "smcup"], check=False)

    def exit_alt_screen(self) -> None:
        if not self.interactive:
            return
        subprocess.run(["tput", "rmcup"], check=False)
