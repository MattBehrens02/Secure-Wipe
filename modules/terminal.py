"""
terminal.py - Destructive wipe command builders for Secure-Wipe

All methods are static and return a list of arguments for safe use with subprocess or run_command.
"""


import subprocess
import time
from dataclasses import dataclass
from typing import Callable
from typing import Any


# --- Command execution logic (from terminal_ui.py) ---
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


def run_command(
    args: list[str],
    timeout: int | None = None,
    check: bool = False,
    progress_callback: Callable[[float], None] | None = None,
) -> CommandResult:
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise CommandRunnerError(f"failed to execute {' '.join(args)}: {exc}") from exc

    start_time = time.monotonic()
    last_progress_emit = start_time

    while process.poll() is None:
        now = time.monotonic()
        elapsed = now - start_time

        if timeout is not None and elapsed > timeout:
            process.kill()
            process.communicate()
            raise CommandRunnerTimeout(f"command timed out: {' '.join(args)}")

        if progress_callback is not None and (now - last_progress_emit) >= 1.0:
            try:
                progress_callback(elapsed)
            except Exception:
                pass
            last_progress_emit = now

        time.sleep(0.2)

    stdout, stderr = process.communicate()

    if check and process.returncode != 0:
        cleaned_stderr = (stderr or "").strip()
        message = f"command failed with exit code {process.returncode}: {' '.join(args)}"
        if cleaned_stderr:
            message = f"{message}: {cleaned_stderr}"
        raise CommandRunnerError(message)

    return CommandResult(
        args=list(args),
        returncode=process.returncode,
        stdout=stdout or "",
        stderr=(stderr or "").strip(),
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
        subprocess.run(["clear"], check=False)
        subprocess.run(["tput", "smcup"], check=False)

    def exit_alt_screen(self) -> None:
        if not self.interactive:
            return
        subprocess.run(["tput", "rmcup"], check=False)

    def prompt_choice(self, message: str, choices: list[str], default: int = 0) -> str:
        """Prompt user to choose from a list of options.
        
        Args:
            message: Question to display to the user
            choices: List of option strings
            default: Index of default choice (0-based)
        
        Returns:
            Selected choice string, or default if not interactive
        """
        if not self.interactive:
            return choices[default] if choices else ""
        
        print(f"\n{message}")
        for i, choice in enumerate(choices):
            marker = " (default)" if i == default else ""
            print(f"  [{i + 1}] {choice}{marker}")
        
        while True:
            try:
                user_input = input("Enter choice (1-{}): ".format(len(choices))).strip()
                if not user_input:
                    return choices[default]
                choice_index = int(user_input) - 1
                if 0 <= choice_index < len(choices):
                    return choices[choice_index]
                print(f"Invalid choice. Please enter 1-{len(choices)}.")
            except ValueError:
                print(f"Invalid input. Please enter a number 1-{len(choices)}.")


class WipeCommands:
    @staticmethod
    def luks_format(device, keyfile):
        """Build command to format device as LUKS2 container."""
        return [
            "cryptsetup", "luksFormat",
            "--type", "luks2",
            "--batch-mode",
            "--key-file", keyfile,
            device
        ]

    @staticmethod
    def luks_open(device, keyfile, mapping_name):
        """Build command to open LUKS2 container and create mapping."""
        return [
            "cryptsetup", "open",
            "--key-file", keyfile,
            device,
            mapping_name
        ]

    @staticmethod
    def luks_close(mapping_name):
        """Build command to close LUKS2 mapping."""
        return [
            "cryptsetup", "close", mapping_name
        ]

    @staticmethod
    def scrub(mapped_device, pattern="nnsa"):
        """Build command to scrub (overwrite) mapped device."""
        return [
            "scrub", "-f", "-p", pattern, mapped_device
        ]

    @staticmethod
    def destroy_luks_header(device):
        """Build command to erase LUKS header from device."""
        return [
            "cryptsetup", "erase", device
        ]

    @staticmethod
    def wipefs(device):
        """Build command to remove all filesystem signatures from device."""
        return [
            "wipefs", "--all", "--force", device
        ]
