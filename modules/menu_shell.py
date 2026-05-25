from modules import version
from modules.config import load_config
from modules import recovery
from modules.terminal import get_adaptive_menu_width
from pathlib import Path
from datetime import datetime, timezone
import subprocess

MENU_WIDTH_MIN = 88
MENU_WIDTH_DEFAULT = 108
MENU_WIDTH_MAX = 120

MENU_OPTIONS = [
    "Start Job",
    "Restart Pending Jobs",
	"View Reports",
	"Configuration",
    "Maintenance",
]


def _menu_row(width: int, text: str = "") -> None:
    print("|" + str(text)[: width - 2].ljust(width - 2) + "|")


def _section_title(width: int, title: str) -> None:
    content = f" {title} "
    padding = max(0, (width - 2 - len(content)) // 2)
    _menu_row(width, " " * padding + content)

def _menu_width() -> int:
    return get_adaptive_menu_width(
        min_width=MENU_WIDTH_MIN,
        default_width=MENU_WIDTH_DEFAULT,
        max_width=MENU_WIDTH_MAX,
    )


def print_line(width: int):
    print("+" + "-" * (width - 2) + "+")

def header(width: int):
    print_line(width)
    _section_title(width, "SecureWipe Operations Console")
    title = version.AppVersion.app_name + " - " + version.AppVersion.app_version
    _section_title(width, title)
    print_line(width)

def environment_info(width: int):
    config = load_config()
    dry_run = "ON" if config.runtime.dry_run else "OFF"
    upload_enabled = "ON" if config.upload.enabled else "OFF"
    logging_level = config.logging.level.upper()
    current_time = datetime.now().strftime("%b %d, %Y %I:%M %p")

    state_dir = getattr(getattr(config, "paths", object()), "state_dir", "./state")
    reports_dir = Path(getattr(getattr(config, "paths", object()), "reports_dir", "./reports"))
    lock_file_path = getattr(getattr(config, "recovery", object()), "lock_file_path", str(Path(state_dir) / "wipe.lock"))
    lock_stale_seconds = int(getattr(getattr(config, "recovery", object()), "lock_stale_seconds", 7200))

    pending_states = len(recovery.list_incomplete_states(state_dir))
    queue_file = reports_dir.parent / "state" / ".upload_queue"
    pending_uploads = 0
    if queue_file.exists():
        try:
            pending_uploads = len([line for line in queue_file.read_text(encoding="utf-8").splitlines() if line.strip()])
        except OSError:
            pending_uploads = 0

    lock_path = Path(lock_file_path)
    if not lock_path.exists():
        lock_needs_clear = "NO"
    else:
        try:
            lock_age_seconds = (datetime.now(timezone.utc) - datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)).total_seconds()
            lock_needs_clear = "YES" if lock_age_seconds > lock_stale_seconds else "NO"
        except OSError:
            lock_needs_clear = "YES"

    column_width = (width - 2 - 4) // 2
    info_rows = [
        (f" Current Time: {current_time}", f"Dry Run: {dry_run}"),
        (f" Upload Enabled: {upload_enabled}", f"Logging Level: {logging_level}"),
        (f" Pending States: {pending_states}", f"Pending Uploads: {pending_uploads}"),
        (f" Lock Needs Clear: {lock_needs_clear}", ""),
    ]

    _section_title(width, "System Status")
    print_line(width)

    for left, right in info_rows:
        inner = f"{left.ljust(column_width)} || {right.ljust(column_width)}"
        _menu_row(width, inner)

    print_line(width)

def print_options(width: int):
    _section_title(width, "Actions")
    print_line(width)

    for idx, option in enumerate(MENU_OPTIONS, start=1):
        option_line = f" [{idx}] {option}"
        _menu_row(width, option_line)

    quit_option = " [Q] Quit"
    _menu_row(width, quit_option)
    print_line(width)

def print_menu():
    width = _menu_width()
    header(width)
    environment_info(width)
    print_options(width)


def _clear_if_prod() -> None:
    cfg = load_config()
    if getattr(getattr(cfg, "runtime", object()), "environment", "dev") == "prod":
        subprocess.run(["clear"], check=False)

def run():
    decided = False
    
    while not decided:
        _clear_if_prod()
        print_menu()
        option = input("  Select option: ")

        if option.lower() == "q":
            print("Exiting...")
            decided = True
            return -1

        elif option in {"1", "2", "3", "4", "5"}:
            decided = True
            return int(option)

        else: 
            print("Invalid option. Please try again.")

