# Ensure required runtime directories exist.
from pathlib import Path
import sys
from modules import config

app_config = config.load_config()

def ensure_runtime_directories(config: config.AppConfig) -> None:
    output_root = str(getattr(config.paths, "output_root", "") or "").strip()
    directories_to_ensure: list[Path] = []

    if output_root:
        directories_to_ensure.append(Path(output_root))

    for dir_attr in ("logs_dir", "reports_dir", "state_dir", "temp_dir"):
        directories_to_ensure.append(Path(getattr(config.paths, dir_attr)))

    for dir_path in directories_to_ensure:
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created missing directory: {dir_path}")
            except PermissionError:
                print(f"Warning: cannot create directory {dir_path} (permission denied) — skipping.", file=sys.stderr)
