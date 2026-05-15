"""
terminal.py - Destructive wipe command builders for Secure-Wipe

All methods are static and return a list of arguments for safe use with subprocess or run_command.
"""


import subprocess
from dataclasses import dataclass
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
