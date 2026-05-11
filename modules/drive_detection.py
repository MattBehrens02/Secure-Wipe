import subprocess, json
from dataclasses import dataclass

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

def _normalize_drive_data(drive_data: dict) -> Drive:
    return Drive(
        name=drive_data.get("name", "") or "",
        path=drive_data.get("path", "") or "",
        size=drive_data.get("size", "") or "",
        model=(drive_data.get("model", "") or "").strip(),
        vendor=(drive_data.get("vendor", "") or "").strip(),
        serial=drive_data.get("serial", "") or "",
        type=drive_data.get("type", "") or "",
        mountpoints=drive_data.get("mountpoints", []),
        removable=bool(drive_data.get("removable", 0)),
        transport=drive_data.get("transport", "") or "",
    )

def print_disk_menu(drives: list[Drive]) -> None:
    print("Available Drives:\n")
    menu_index = 0

    print(f" {'Drive Name':<37} {'Path':<15} {'Size':>6} Type")
    print("-" * 70)
    for drive in drives:
        menu_index += 1
        menu_index_str = f"[{menu_index}]"
        drive_name = f"{drive.vendor} {drive.model}".strip() or "Unknown Drive"
        print(f" {menu_index_str:>4} {drive_name:<32} {drive.path:<15} {drive.size:>6} ({'Removable' if drive.removable else 'Fixed'})")
        
    print("\nEnter the number corresponding to the drive you want to wipe, or 'q' to quit.")

def detect_drives():
    result = subprocess.run(
        ['lsblk', '--json', '--output', 'NAME,PATH,SIZE,MODEL,VENDOR,SERIAL,TYPE,MOUNTPOINTS,RM,TRAN'],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    fetched_drives = json.loads(result.stdout)
    
    formatted_drives = [
        _normalize_drive_data(drive)
            for drive in fetched_drives.get("blockdevices", [])
        ]

    print_disk_menu(formatted_drives)
    choice = input("Your choice: ").strip()
    if choice.lower() == 'q':
        print("Exiting.")
        return []

    return formatted_drives