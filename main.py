import subprocess
import sys
import tomllib

from modules import config, drive_detection, recovery, reporting, uploader, verification, wipe_engine


def main() -> int:
	try:
		app_config = config.load_config()
	except (ValueError, tomllib.TOMLDecodeError, OSError) as exc:
		print(f"Configuration error: {exc}", file=sys.stderr)
		return 1

	if not app_config.runtime.environment == "dev": 
		subprocess.run(["tput", "smcup"], check=False) # Switch to alternate screen buffer

	try: 
		print(
			"Loaded configuration: "
			f"environment={app_config.runtime.environment}, "
			f"dry_run={app_config.runtime.dry_run}"
		)

		selected_drives = drive_detection.run(app_config)
		if selected_drives == []:
			print("No drives detected.")
			return 1

		# wipe_drives(selected_drive, app_config.wipe)
	
	finally:
		if not app_config.runtime.environment == "dev":
			subprocess.run(["tput", "rmcup"], check=False) # Restore original screen buffer

	return 0


if __name__ == "__main__":
	raise SystemExit(main())