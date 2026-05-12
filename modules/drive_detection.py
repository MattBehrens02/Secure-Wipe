import json
import subprocess
from dataclasses import dataclass
from typing import Any

from modules.smartctl import collect_smart_snapshot
from modules.smartctl import collect_smart_info

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
    smart_data: dict[str, Any] | None = None

# Main function to run the drive detection and selection workflow. 
# Returns a list of selected Drive instances or an empty list if no drives were selected or an error occurred.
def run(app_config: Any = None):
    try:
        fetched_drives = detect_drives()
    except DriveDetectionError as exc:
        print(f"Drive detection error: {exc}")
        return []

    formatted_drives = normalize_drives(fetched_drives)

    if app_config is not None:
        formatted_drives = _apply_safety_policy(formatted_drives, app_config)

    selected_drives = get_user_input(formatted_drives)
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

    if app_config is not None and not confirm_all_drives(selected_drives, app_config):
        print("Confirmation failed. Exiting.")
        return []

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

    return Drive(
        name=drive_data.get("name", "") or "",
        path=drive_data.get("path", "") or "",
        size=drive_data.get("size", "") or "",
        model=(drive_data.get("model", "") or "").strip(),
        vendor=(drive_data.get("vendor", "") or "").strip(),
        serial=drive_data.get("serial", "") or "",
        type=drive_data.get("type", "") or "",
        mountpoints=mountpoints,
        removable=bool(drive_data.get("rm", 0)),
        transport=drive_data.get("tran", "") or "",
    )


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
def print_menu_options(drives: list[Drive]) -> None:
    print("\nAvailable Drives:\n")
    menu_index = 0

    print(f" {'Drive Name':<37} {'Path':<15} {'Size':>6} Type")
    print("-" * 70)

    # List drives with indices
    for drive in drives:
        menu_index += 1
        menu_index_str = f"[{menu_index}]"
        drive_name = f"{drive.vendor} {drive.model}".strip() or "Unknown Drive"
        print(f" {menu_index_str:>4} {drive_name:<32} {drive.path:<15} {drive.size:>6} ({'Removable' if drive.removable else 'Fixed'})")

# Prompts the user to select one or more drives from the menu and returns the selected Drive instances.
def get_user_input(formatted_drives: list[Drive]) -> list[Drive]:
    if not formatted_drives:
        print("No eligible disk drives detected.")
        return []

    valid_input = False

    while not valid_input:
        print_menu_options(formatted_drives)
        print("\nEnter the number(s) corresponding to the drive(s) you want to wipe, separated by commas, or 'q' to quit.")
        choice = input("Your choice: ").strip()

        if 'q' in choice.lower():
            print("Exiting.")
            return []
        
        try:
            choices = [c.strip() for c in choice.split(',') if c.strip()]
            selected_drives = []
            valid = True
            
            for c in choices:
                selected_index = int(c) - 1
                if 0 <= selected_index < len(formatted_drives):
                    selected_drives.append(formatted_drives[selected_index])
                else:
                    print("Invalid selection. Please enter valid numbers from the menu.")
                    valid = False
                    break
            
            if valid and selected_drives:
                return selected_drives
        except ValueError:
            print("Invalid input. Please enter comma-separated numbers corresponding to the drives or 'q' to quit.")

    return []

# Detects drives using lsblk and returns the parsed JSON output. Raises DriveDetectionError on failure.
def detect_drives() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ['lsblk', '--json', '--output', 'NAME,PATH,SIZE,MODEL,VENDOR,SERIAL,TYPE,MOUNTPOINTS,RM,TRAN'],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise DriveDetectionError("lsblk timed out while detecting drives") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        message = f"lsblk failed with exit code {exc.returncode}"
        if stderr:
            message = f"{message}: {stderr}"
        raise DriveDetectionError(message) from exc
    except OSError as exc:
        raise DriveDetectionError(f"failed to execute lsblk: {exc}") from exc

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

# Ask the user for confirmation before proceeding with wiping the selected drives.
# The number of confirmation steps is controlled by app_config.safety.confirmation_steps.
def confirm_all_drives(selected_drives: list[Drive], app_config: Any) -> bool:
    steps = int(app_config.safety.confirmation_steps)

    if steps <= 0:
        return True
    
    subprocess.run("clear")  # Clear the screen to make the warning more prominent

    if len(selected_drives) > 1:
        print("\nWARNING: You have selected multiple drives")
        print("\nYou have selected the following drives for wiping:")
    else:
        print("\nYou have selected the following drive for wiping:")

    for drive in selected_drives:
        print(f"- {drive.path} ({drive.size}, {'Removable' if drive.removable else 'Fixed'})")

    if steps >= 1:
        first = input("\nProceed with wiping these drives? [y/N]: ").strip().lower()
        if first not in {"y", "yes"}:
            return False
        
    if steps >= 2:
        second = input("Type WIPE to confirm wiping the selected drives: ").strip().lower()
        if second != "wipe":
            return False

    return True