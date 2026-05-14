# Ensure required runtime directories exist.
from pathlib import Path
import sys
from modules import config

app_config = config.load_config()

def ensure_runtime_directories(config: config.AppConfig) -> None:
    for dir_attr in ("logs_dir", "reports_dir", "state_dir", "temp_dir"):
        dir_path = Path(getattr(app_config.paths, dir_attr))
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"Created missing directory: {dir_path}")
            except PermissionError:
                print(f"Warning: cannot create directory {dir_path} (permission denied) — skipping.", file=sys.stderr)
