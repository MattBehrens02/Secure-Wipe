from modules import version
from modules.config import load_config
from modules import recovery
from pathlib import Path
from datetime import datetime, timezone

MENU_WIDTH = 80 # The width of the menu shell, feel free to adjust as needed

MENU_OPTIONS = [
    "Start Job",
    "Restart Pending Jobs",
	"View Reports",
	"Configuration",
    "Maintenance",
]

def print_line():
    print("+" + "-" * (MENU_WIDTH - 2) + "+")

def header():
    print_line()
    
    #calculate the padding for centering the header
    header_padding = (MENU_WIDTH - 2 - len(version.AppVersion.app_name + " - " + version.AppVersion.app_version)) // 2
    header_line = "|" + " " * header_padding + version.AppVersion.app_name + " - " + version.AppVersion.app_version + " " * (MENU_WIDTH - 2 - header_padding - len(version.AppVersion.app_name + " - " + version.AppVersion.app_version)) + "|"
    print(header_line)

    print_line()

def environment_info():
    config = load_config()
    env = config.runtime.environment
    dry_run = "ON" if config.runtime.dry_run else "OFF"
    upload_enabled = "ON" if config.upload.enabled else "OFF"
    logging_level = config.logging.level.upper()

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

    column_width = (MENU_WIDTH - 2 - 4) // 2
    info_rows = [
        (f" Environment: {env}", f"Dry Run: {dry_run}"),
        (f" Upload Enabled: {upload_enabled}", f"Logging Level: {logging_level}"),
        (f" Pending States: {pending_states}", f"Pending Uploads: {pending_uploads}"),
        (f" Lock Needs Clear: {lock_needs_clear}", ""),
    ]

    for left, right in info_rows:
        inner = f"{left.ljust(column_width)} || {right.ljust(column_width)}"
        print("|" + inner + "|")

    print_line()

def print_options():
    for idx, option in enumerate(MENU_OPTIONS, start=1):
        option_line = f" [{idx}] {option}"
        print("|" + option_line.ljust(MENU_WIDTH - 2) + "|")

    quit_option = " [Q] Quit"

    print("|" + quit_option + " " * (MENU_WIDTH - 2 - len(quit_option)) + "|")
    print_line()

def print_menu():
    header()
    environment_info()
    print_options()

def run():
    decided = False
    
    while not decided:
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

