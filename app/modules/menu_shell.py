from modules import version
from modules.config import AppConfig
from modules import recovery
from modules.terminal import get_adaptive_menu_width
from modules.time_utils import now_for_output_names
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
    "Open Terminal",
    "Shutdown System",
    "Restart System",
    "View Logs",
]


def _menu_row(width: int, text: str = "") -> None:
    print("|" + str(text)[: width - 2].ljust(width - 2) + "|")


def _section_title(width: int, title: str) -> None:
    content = f" {title} "
    padding = max(0, (width - 2 - len(content)) // 2)
    _menu_row(width, " " * padding + content)


def _normalize_nav_input(raw_value: str) -> str:
    return str(raw_value or "").strip().lower()


def parse_submenu_input(
    raw_value: str,
    option_count: int,
    *,
    allow_paging: bool = False,
) -> tuple[str, int | None]:
    """Parse shared submenu navigation commands.

    Returns:
        (action, selected_index)
        - action: one of 'select', 'back', 'next_page', 'prev_page', 'invalid'
        - selected_index: zero-based index when action == 'select', else None
    """

    value = _normalize_nav_input(raw_value)
    if value in {"r", "b", "back", "return"}:
        return "back", None

    if allow_paging and value in {"n", "f", "next", "forward", ">"}:
        return "next_page", None
    if allow_paging and value in {"p", "prev", "previous", "<"}:
        return "prev_page", None

    if value.isdigit():
        selected_index = int(value) - 1
        if 0 <= selected_index < option_count:
            return "select", selected_index

    return "invalid", None


def _submenu_width() -> int:
    return get_adaptive_menu_width(
        min_width=MENU_WIDTH_MIN,
        default_width=MENU_WIDTH_DEFAULT,
        max_width=MENU_WIDTH_MAX,
    )


def _submenu_line(width: int) -> None:
    print("+" + "-" * (width - 2) + "+")


def _submenu_row(width: int, text: str = "") -> None:
    print("|" + str(text)[: width - 2].ljust(width - 2) + "|")


def _submenu_section_title(width: int, title: str) -> None:
    content = f" {title} "
    padding = max(0, (width - 2 - len(content)) // 2)
    _submenu_row(width, " " * padding + content)


def print_submenu(title: str, options: list[str], footer: str) -> None:
    width = _submenu_width()
    _submenu_line(width)
    _submenu_section_title(width, title)
    _submenu_line(width)
    _submenu_section_title(width, "Options")
    _submenu_line(width)
    for index, option in enumerate(options, start=1):
        label = f" [{index}] {option}"
        _submenu_row(width, label)
    _submenu_line(width)
    _submenu_section_title(width, "Navigation")
    _submenu_row(width, f" {footer}")
    _submenu_line(width)

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
    _section_title(width, "Secure-Wipe Operations Console")
    title = version.AppVersion.app_name + " - " + version.AppVersion.app_version
    _section_title(width, title)
    print_line(width)

def environment_info(width: int, app_config: AppConfig | None = None):
    config = app_config if app_config is not None else AppConfig()
    dry_run = "ON" if config.runtime.dry_run else "OFF"
    upload_enabled = "ON" if config.upload.enabled else "OFF"
    logging_level = config.logging.level.upper()
    current_time = now_for_output_names(config).strftime("%b %d, %Y %I:%M %p")

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

    print_line(width)


def print_alerts(width: int, alerts: list[str] | None):
    if not alerts:
        return

    _section_title(width, "Alerts")
    print_line(width)
    for message in alerts:
        _menu_row(width, f" ! {message}")
    print_line(width)


def print_menu(app_config: AppConfig | None = None, alerts: list[str] | None = None):
    width = _menu_width()
    header(width)
    environment_info(width, app_config)
    print_options(width)
    print_alerts(width, alerts)


def _clear_if_prod(app_config: AppConfig | None = None) -> None:
    cfg = app_config if app_config is not None else AppConfig()
    if getattr(getattr(cfg, "runtime", object()), "environment", "dev") == "prod":
        subprocess.run(["clear"], check=False)


def run(app_config: AppConfig | None = None, alerts: list[str] | None = None):
    decided = False
    
    while not decided:
        _clear_if_prod(app_config)
        print_menu(app_config, alerts)
        option = input("  Select option: ")

        if option in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            decided = True
            return int(option)

        else: 
            print("Invalid option. Please try again.")

