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

	print(
		"Loaded configuration: "
		f"environment={app_config.runtime.environment}, "
		f"dry_run={app_config.runtime.dry_run}"
	)

	# TODO: Integrate wipe workflow modules as implementation progresses.
	# (wipe_engine, recovery, verification, reporting, uploader)

	drives = drive_detection.detect_drives()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())