import json
from dataclasses import dataclass
from typing import Any

from modules import config
from modules.smartctl import collect_smart_snapshot
from modules.smartctl import collect_smart_info
from modules import header
from modules.terminal import (
    CommandRunnerError,
    CommandRunnerTimeout,
    TerminalUI,
    get_adaptive_menu_width,
    run_command,
)


DRIVE_MENU_WIDTH_MIN = 88
DRIVE_MENU_WIDTH_DEFAULT = 108
DRIVE_MENU_WIDTH_MAX = 120
DRIVE_PAGE_SIZE = 10

_TABLE_ID_WIDTH = 3
_TABLE_PATH_WIDTH = 12
_TABLE_SIZE_WIDTH = 8
_TABLE_MEDIA_WIDTH = 7
_TABLE_FLAGS_WIDTH = 11

class DriveDetectionError(Exception):
    pass

@dataclass
class Drive:
    name: str
    path: str
    size: str
    model: str
    vendor: str
    serial: str
    type: str
    mountpoints: list
    removable: bool
    transport: str
    rotational: bool | None
    size_bytes: int | None = None
    media_type: str = "Unknown"
    is_hdd: bool = False
    smart_data: dict[str, Any] | None = None


def _coerce_rotational(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _coerce_size_bytes(value: Any) -> int | None:
    if value is None:
        return None
    try:
        size_bytes = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return size_bytes if size_bytes > 0 else None


def _format_display_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return ""

    units = ["B", "K", "M", "G", "T", "P"]
    size_value = float(size_bytes)
    unit_index = 0
    while size_value >= 1000 and unit_index < len(units) - 1:
        size_value /= 1000.0
        unit_index += 1

    if unit_index == 0 or size_value >= 100:
        return f"{size_value:.0f}{units[unit_index]}"
    return f"{size_value:.1f}{units[unit_index]}"


def _infer_media_type(drive: Drive) -> str:
    transport = (drive.transport or "").strip().lower()
    name_blob = " ".join(
        [
            (drive.name or "").lower(),
            (drive.vendor or "").lower(),
            (drive.model or "").lower(),
        ]
    )
    if transport == "nvme" or drive.path.startswith("/dev/nvme"):
        return "NVMe"

    flash_markers = (
        "flash",
        "thumb",
        "pen",
        "ufd",
        "microsd",
        "sd",
        "sdxc",
        "sdhc",
    )
    looks_like_flash = any(marker in name_blob for marker in flash_markers)

    if drive.removable and transport == "usb":
        if drive.rotational is False or looks_like_flash:
            return "Flash"
        if drive.rotational is True:
            return "USB-HDD"
        return "USB"

    if drive.rotational is True:
        drive.is_hdd = True
        return "HDD"
    if drive.rotational is False:
        return "SSD"

    smart_data = drive.smart_data if isinstance(drive.smart_data, dict) else None
    if smart_data:
        if isinstance(smart_data.get("nvme_smart_health_information_log"), dict):
            return "NVMe"

        rotation_rate = smart_data.get("rotation_rate")
        if isinstance(rotation_rate, (int, float)) and rotation_rate > 0:
            drive.is_hdd = True
            return "HDD"

    return "Unknown"

# Main function to run the drive detection and selection workflow. 
# Returns a list of selected Drive instances or an empty list if no drives were selected or an error occurred.
def run(app_config: Any = None, terminal_ui: TerminalUI | None = None):
    terminal_ui = terminal_ui or TerminalUI.from_config(app_config)

    try:
        fetched_drives = detect_drives()
    except DriveDetectionError as exc:
        print(f"Drive detection error: {exc}")
        return []

    formatted_drives = normalize_drives(fetched_drives)

    if app_config is not None:
        formatted_drives = _apply_safety_policy(formatted_drives, app_config)

    selectionLoop = True
    while selectionLoop:

        selected_drives = get_user_input(formatted_drives, terminal_ui, app_config)
        if not selected_drives:
            print("No drives selected. Exiting.")
            return []

        # Show a single warning if any selected drive is removable or mounted
        if app_config is not None:
            warn_if_risky_drives(selected_drives)

        if app_config is not None and app_config.drive_detection.collect_smart_info:
            smart_snapshot = collect_smart_snapshot([drive.path for drive in selected_drives])
            for drive in selected_drives:
                drive.smart_data = smart_snapshot.get(drive.path)
                drive.media_type = _infer_media_type(drive)

        if app_config is not None and not confirm_all_drives(selected_drives, app_config, terminal_ui):
            print("Confirmation failed.")
            selectionLoop = True
        else:
            selectionLoop = False

    print(f"Selected drive(s) for wiping: {[drive.path for drive in selected_drives]}")
    return selected_drives

# Return True if the drive has any mountpoints (i.e., is mounted), otherwise False.
def _is_mounted(drive: Drive) -> bool:
    return bool(drive.mountpoints)

# Check if a drive is blocked by safety configuration (removable/mounted) and return a tuple of (is_blocked, reason).
def _is_blocked_by_safety_modes(drive: Drive, app_config: Any) -> tuple[bool, str]:
    safety = app_config.safety

    if drive.removable and safety.removable_drive_mode == "deny":
        return True, "removable drives are set to deny"

    if _is_mounted(drive) and safety.mount_handling_mode == "deny":
        return True, "mounted drives are set to deny"

    return False, ""

# Filter out drives that are blocked by safety policy (removable/mounted) and return the list of eligible drives.
def _apply_safety_policy(formatted_drives: list[Drive], app_config: Any) -> list[Drive]:
    eligible_drives: list[Drive] = []

    for drive in formatted_drives:
        blocked, reason = _is_blocked_by_safety_modes(drive, app_config)
        if blocked:
            print(f"Skipping {drive.path}: {reason}.")
            continue
        eligible_drives.append(drive)

    return eligible_drives

# Normalizes raw drive data from lsblk into a consistent Drive dataclass instance.
def normalize_drive_data(drive_data: Any) -> Drive | None:
    # Ignore unexpected items and non-disk entries.
    if not isinstance(drive_data, dict) or drive_data.get("type") != "disk":
        return None

    raw_mountpoints = drive_data.get("mountpoints") or []
    mountpoints = [mp for mp in raw_mountpoints if mp] if isinstance(raw_mountpoints, list) else []
    size_bytes = _coerce_size_bytes(drive_data.get("size"))
    display_size = _format_display_size(size_bytes) or (drive_data.get("size", "") or "")

    normalized = Drive(
        name=drive_data.get("name", "") or "",
        path=drive_data.get("path", "") or "",
        size=display_size,
        model=(drive_data.get("model", "") or "").strip(),
        vendor=(drive_data.get("vendor", "") or "").strip(),
        serial=drive_data.get("serial", "") or "",
        type=drive_data.get("type", "") or "",
        mountpoints=mountpoints,
        removable=bool(drive_data.get("rm", 0)),
        transport=drive_data.get("tran", "") or "",
        rotational=_coerce_rotational(drive_data.get("rota")),
        size_bytes=size_bytes,
    )

    normalized.media_type = _infer_media_type(normalized)
    return normalized


def normalize_drives(fetched_drives: Any) -> list[Drive]:
    """Convert raw lsblk payload into a list of normalized disk Drive objects."""
    if not isinstance(fetched_drives, dict):
        return []

    blockdevices = fetched_drives.get("blockdevices", [])
    if not isinstance(blockdevices, list):
        return []

    return [
        normalized
        for normalized in (normalize_drive_data(drive) for drive in blockdevices)
        if normalized is not None
    ]

# Print a menu of available drives for user selection.
def _menu_line() -> None:
    width = _drive_menu_width()
    print("+" + "-" * (width - 2) + "+")


def _menu_row(text: str) -> None:
    width = _drive_menu_width()
    print("|" + text[: width - 2].ljust(width - 2) + "|")


def _drive_menu_width() -> int:
    return get_adaptive_menu_width(
        min_width=DRIVE_MENU_WIDTH_MIN,
        default_width=DRIVE_MENU_WIDTH_DEFAULT,
        max_width=DRIVE_MENU_WIDTH_MAX,
    )


def _drive_table_model_width() -> int:
    # Account for six columns and five separators: " | "
    separator_width = 5 * 3
    occupied = (
        _TABLE_ID_WIDTH
        + _TABLE_PATH_WIDTH
        + _TABLE_SIZE_WIDTH
        + _TABLE_MEDIA_WIDTH
        + _TABLE_FLAGS_WIDTH
        + separator_width
    )
    menu_width = _drive_menu_width()
    return max(10, (menu_width - 2) - occupied)


def _clip_table_value(value: str, width: int) -> str:
    text = str(value or "")
    if len(text) <= width:
        return text.ljust(width)
    if width <= 1:
        return text[:width]
    return (text[: width - 1] + "~")


def _drive_table_header() -> str:
    model_width = _drive_table_model_width()
    return (
        f"{_clip_table_value('ID', _TABLE_ID_WIDTH)} | "
        f"{_clip_table_value('Path', _TABLE_PATH_WIDTH)} | "
        f"{_clip_table_value('Size', _TABLE_SIZE_WIDTH)} | "
        f"{_clip_table_value('Media', _TABLE_MEDIA_WIDTH)} | "
        f"{_clip_table_value('Flags', _TABLE_FLAGS_WIDTH)} | "
        f"{_clip_table_value('Model', model_width)}"
    )


def _drive_table_rule() -> str:
    model_width = _drive_table_model_width()
    return (
        f"{'-' * _TABLE_ID_WIDTH}-+-"
        f"{'-' * _TABLE_PATH_WIDTH}-+-"
        f"{'-' * _TABLE_SIZE_WIDTH}-+-"
        f"{'-' * _TABLE_MEDIA_WIDTH}-+-"
        f"{'-' * _TABLE_FLAGS_WIDTH}-+-"
        f"{'-' * model_width}"
    )


def _drive_table_row(menu_index: int, drive: Drive) -> str:
    model_width = _drive_table_model_width()
    flags = "removable" if drive.removable else "fixed"
    model = f"{drive.vendor} {drive.model}".strip() or "Unknown Drive"
    return (
        f"{_clip_table_value(str(menu_index), _TABLE_ID_WIDTH)} | "
        f"{_clip_table_value(drive.path, _TABLE_PATH_WIDTH)} | "
        f"{_clip_table_value(drive.size, _TABLE_SIZE_WIDTH)} | "
        f"{_clip_table_value(drive.media_type, _TABLE_MEDIA_WIDTH)} | "
        f"{_clip_table_value(flags, _TABLE_FLAGS_WIDTH)} | "
        f"{_clip_table_value(model, model_width)}"
    )


def _normalize_nav_input(raw_value: str) -> str:
    return str(raw_value or "").strip().lower()


def _parse_drive_menu_input(raw_value: str) -> tuple[str, str]:
    """Parse shared drive-menu navigation commands.

    Returns:
        (action, normalized_value)
        action: 'select', 'back', 'next_page', 'prev_page'
    """
    value = _normalize_nav_input(raw_value)
    if value in {"q", "r", "b", "back", "return"}:
        return "back", value
    if value in {"n", "f", "next", "forward", ">"}:
        return "next_page", value
    if value in {"p", "prev", "previous", "<"}:
        return "prev_page", value
    return "select", value


def print_menu_options(drives: list[Drive], page_index: int = 0, page_size: int = DRIVE_PAGE_SIZE) -> None:
    page_count = max(1, (len(drives) + page_size - 1) // page_size)
    page_index = max(0, min(page_index, page_count - 1))
    start = page_index * page_size
    end = start + page_size
    page_drives = drives[start:end]

    header.print_header()
    print("\n")
    _menu_line()
    _menu_row(" Drive Selection ")
    _menu_line()
    _menu_row(_drive_table_header())
    _menu_row(_drive_table_rule())

    for offset, drive in enumerate(page_drives):
        menu_index = start + offset + 1
        _menu_row(_drive_table_row(menu_index, drive))

    _menu_line()
    _menu_row(f" Page {page_index + 1}/{page_count} | N/F next | P previous | B/R/Q return")
    _menu_row(" Enter drive number(s) separated by commas to select")
    _menu_line()


def _is_prod(app_config: Any) -> bool:
    if app_config is None:
        return False
    return getattr(getattr(app_config, "runtime", object()), "environment", "dev") == "prod"

# Prompts the user to select one or more drives from the menu and returns the selected Drive instances.
def get_user_input(formatted_drives: list[Drive], terminal_ui: TerminalUI, app_config: Any = None) -> list[Drive]:
    if not formatted_drives:
        print("No eligible disk drives detected.")
        return []

    page_count = max(1, (len(formatted_drives) + DRIVE_PAGE_SIZE - 1) // DRIVE_PAGE_SIZE)
    page_index = 0

    while True:
        if _is_prod(app_config):
            terminal_ui.clear()

        print_menu_options(formatted_drives, page_index=page_index, page_size=DRIVE_PAGE_SIZE)
        choice = input("Select drive(s): ").strip()
        action, parsed_value = _parse_drive_menu_input(choice)

        if action == "back":
            print("Exiting.")
            return []
        if action == "next_page":
            if page_index < page_count - 1:
                page_index += 1
            continue
        if action == "prev_page":
            if page_index > 0:
                page_index -= 1
            continue

        try:
            choices = [c.strip() for c in parsed_value.split(',') if c.strip()]
            selected_drives = []
            valid = True
            
            for c in choices:
                selected_index = int(c) - 1
                if 0 <= selected_index < len(formatted_drives):
                    selected_drives.append(formatted_drives[selected_index])
                else:
                    terminal_ui.clear()
                    print("\nInvalid selection. Please enter valid numbers from the menu.")
                    valid = False
                    break
            
            if valid and selected_drives:
                return selected_drives
            
        except ValueError:
            terminal_ui.clear()
            print("\nInvalid input. Enter numbers, N/F for next page, P for previous page, or B/R/Q to return.")

# Detects drives using lsblk and returns the parsed JSON output. Raises DriveDetectionError on failure.
def detect_drives() -> dict[str, Any]:
    try:
        result = run_command(
            ['lsblk', '--bytes', '--json', '--output', 'NAME,PATH,SIZE,MODEL,VENDOR,SERIAL,TYPE,MOUNTPOINTS,RM,TRAN,ROTA'],
            timeout=10,
            check=True,
        )
    except CommandRunnerTimeout as exc:
        raise DriveDetectionError("lsblk timed out while detecting drives") from exc
    except CommandRunnerError as exc:
        raise DriveDetectionError(str(exc)) from exc

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DriveDetectionError(f"failed to parse lsblk output: {exc}") from exc

def warn_if_risky_drives(selected_drives: list[Drive]) -> None:
    risky = [d for d in selected_drives if d.removable or _is_mounted(d)]
    if risky:
        print("\nWARNING: You have selected one or more removable or mounted drives. Wiping these may be risky!")
        for d in risky:
            flags = []
            if d.removable:
                flags.append("removable")
            if _is_mounted(d):
                flags.append("mounted")
            print(f"- {d.path} ({', '.join(flags)})")


def _print_confirm_risk_banner(selected_drives: list[Drive]) -> None:
    risky = [d for d in selected_drives if d.removable or _is_mounted(d)]
    if not risky:
        return

    print("\nDANGER: REMOVABLE OR MOUNTED DRIVES SELECTED - HIGH RISK OPERATION")


def _render_confirmation_screen(selected_drives: list[Drive], steps: int) -> None:
    _menu_line()
    _menu_row(" Wipe Confirmation ")
    _menu_line()

    risky = [d for d in selected_drives if d.removable or _is_mounted(d)]
    if risky:
        _menu_row(" DANGER: Removable or mounted drives selected")
        for drive in risky:
            flags = []
            if drive.removable:
                flags.append("removable")
            if _is_mounted(drive):
                flags.append("mounted")
            _menu_row(f" - {drive.path} ({', '.join(flags)})")
        _menu_line()

    if len(selected_drives) > 1:
        _menu_row(" You have selected multiple drives for wiping")
    else:
        _menu_row(" You have selected one drive for wiping")
    _menu_line()

    for drive in selected_drives:
        drive_type = "Removable" if drive.removable else "Fixed"
        _menu_row(f" - {drive.path} | {drive.size} | {drive_type}")

    _menu_line()
    if steps >= 1:
        _menu_row(" Step 1: confirm with [y/N]")
    if steps >= 2:
        _menu_row(" Step 2: type WIPE to continue")
    _menu_line()

# Ask the user for confirmation before proceeding with wiping the selected drives.
# The number of confirmation steps is controlled by app_config.safety.confirmation_steps.
def confirm_all_drives(selected_drives: list[Drive], app_config: Any, terminal_ui: TerminalUI) -> bool:
    steps = int(app_config.safety.confirmation_steps)

    if steps <= 0:
        return True
    
    terminal_ui.clear()

    _render_confirmation_screen(selected_drives, steps)

    if steps >= 1:
        first = input("\nProceed with wiping these drives? [y/N]: ").strip().lower()
        if first not in {"y", "yes"}:
            return False
        
    if steps >= 2:
        second = input("Type WIPE to confirm wiping the selected drives: ").strip().lower()
        if second != "wipe":
            return False

    return True