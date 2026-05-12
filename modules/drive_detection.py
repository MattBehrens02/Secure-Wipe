import json
import subprocess
from dataclasses import dataclass
from typing import Any

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


def _is_mounted(drive: Drive) -> bool:
    return bool(drive.mountpoints)


def _is_blocked_by_safety_modes(drive: Drive, app_config: Any) -> tuple[bool, str]:
    safety = app_config.safety

    if drive.removable and safety.removable_drive_mode == "deny":
        return True, "removable drives are set to deny"

    if _is_mounted(drive) and safety.mount_handling_mode == "deny":
        return True, "mounted drives are set to deny"

    return False, ""


def _requires_extra_confirmation(drive: Drive, app_config: Any) -> bool:
    safety = app_config.safety

    removable_confirm = drive.removable and safety.removable_drive_mode == "confirm"
    mounted_confirm = _is_mounted(drive) and safety.mount_handling_mode == "confirm"
    return removable_confirm or mounted_confirm


def _confirm_risky_selections(selected_drives: list[Drive], app_config: Any) -> bool:
    risky_drives = [drive for drive in selected_drives if _requires_extra_confirmation(drive, app_config)]
    if not risky_drives:
        return True

    steps = int(app_config.safety.confirmation_steps)
    if steps <= 0:
        return True

    print("\nWarning: one or more selected drives require extra confirmation based on safety mode.")
    for drive in risky_drives:
        flags = []
        if drive.removable and app_config.safety.removable_drive_mode == "confirm":
            flags.append("removable")
        if _is_mounted(drive) and app_config.safety.mount_handling_mode == "confirm":
            flags.append("mounted")
        flag_text = ", ".join(flags)
        print(f"- {drive.path} ({flag_text})")

    first = input("Proceed with these risky selections? [y/N]: ").strip().lower()
    if first not in {"y", "yes"}:
        return False

    if steps >= 2:
        second = input("Type WIPE to confirm risky selections: ").strip()
        if second != "WIPE":
            return False

    return True


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
def _normalize_drive_data(drive_data: dict) -> Drive:
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

# Displays a user-friendly menu of detected drives and prompts for selection.
def print_menu_options(drives: list[Drive]) -> None:
    print("Available Drives:\n")
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

# Detects drives using lsblk and returns a list of normalized Drive instances.
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

# Main function to run the drive detection and selection workflow. 
# Returns a list of selected Drive instances or an empty list if no drives were selected or an error occurred.
def run(app_config: Any = None):
    try:
        fetched_drives = detect_drives()
    except DriveDetectionError as exc:
        print(f"Drive detection error: {exc}")
        return []

    blockdevices = fetched_drives.get("blockdevices", [])
    formatted_drives = [
        _normalize_drive_data(drive)
        for drive in blockdevices
        if isinstance(drive, dict) and drive.get("type") == "disk"
    ]

    if app_config is not None:
        formatted_drives = _apply_safety_policy(formatted_drives, app_config)

    selected_drives = get_user_input(formatted_drives)
    if not selected_drives:
        print("No drives selected. Exiting.")
        return []

    if app_config is not None and not _confirm_risky_selections(selected_drives, app_config):
        print("Risk confirmation failed. Exiting.")
        return []

    if not _confirm_all_drives(selected_drives):
        print("Global confirmation failed. Exiting.")
        return []

    print(f"Selected drive(s) for wiping: {[drive.path for drive in selected_drives]}")
    return selected_drives

def _confirm_all_drives(selected_drives: list[Drive]) -> bool:
    print("\nYou have selected the following drives:")
    for drive in selected_drives:
        print(f"- {drive.path} ({drive.size}, {'Removable' if drive.removable else 'Fixed'})")

    confirmation = input("Are you sure you want to proceed with these drives? Type 'YES' to confirm: ").strip()
    return confirmation == "YES"