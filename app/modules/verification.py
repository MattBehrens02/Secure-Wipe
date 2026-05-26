import math
import os
import random
from dataclasses import dataclass, field
from typing import Any

from modules.app_logging import log_error, log_info
from modules.smartctl import SmartctlError, collect_smart_info, is_smartctl_available
from modules.terminal import CommandRunnerError, CommandRunnerTimeout, run_command


class VerificationError(Exception):
	"""Raised when a verification check cannot be completed."""


@dataclass
class VerificationResult:
	"""Structured result for post-wipe verification."""

	status: str
	checks_passed: list[str] = field(default_factory=list)
	checks_failed: list[str] = field(default_factory=list)
	verification_errors: list[str] = field(default_factory=list)
	smart_before: dict[str, Any] | None = None
	smart_after: dict[str, Any] | None = None
	check_details: dict[str, Any] = field(default_factory=dict)


def _resolve_device_path(drive: Any) -> str:
	"""Return the device path from a drive-like object or raw path string."""
	if isinstance(drive, str):
		return drive
	return str(getattr(drive, "path", ""))


def _resolve_device_size_bytes(drive: Any) -> int:
	"""Best-effort resolution of device size in bytes."""
	size_candidates = [
		getattr(drive, "size_bytes", None),
		getattr(drive, "size", None),
	]

	for candidate in size_candidates:
		try:
			if candidate is not None:
				return int(candidate)
		except (TypeError, ValueError):
			continue

	device_path = _resolve_device_path(drive)
	if device_path and os.path.exists(device_path):
		try:
			return os.path.getsize(device_path)
		except OSError:
			return 0

	return 0


def _is_hdd_drive(drive: Any) -> bool:
	"""Best-effort HDD classification used for zero-pass validation."""
	if bool(getattr(drive, "is_hdd", False)):
		return True

	media_type = str(getattr(drive, "media_type", "")).upper()
	return media_type == "HDD"


def _compute_sample_count(size_bytes: int, sample_ratio: float, max_samples: int = 16) -> int:
	"""Compute a bounded sample count from device size and configured ratio."""
	if size_bytes <= 0:
		return 0

	gibibytes = max(1.0, size_bytes / float(1024 ** 3))
	sample_count = math.ceil(gibibytes * max(sample_ratio, 0.0))
	return max(1, min(max_samples, sample_count))


def _build_sample_offsets(size_bytes: int, sample_count: int, block_size: int) -> list[int]:
	"""Build random sample offsets aligned to the chosen block size."""
	if size_bytes < block_size or sample_count <= 0:
		return [0] if size_bytes > 0 else []

	max_offset = size_bytes - block_size
	slot_count = (max_offset // block_size) + 1
	if sample_count >= slot_count:
		return [index * block_size for index in range(slot_count)]

	generator = random.SystemRandom()
	sampled_slots = sorted(generator.sample(range(slot_count), sample_count))
	return [slot * block_size for slot in sampled_slots]


def _serialize_command(args: list[str]) -> str:
	return " ".join(args)


def check_luks_header_destroyed(
	device_path: str,
	dry_run: bool = False,
	timeout: int = 10,
) -> tuple[bool, dict[str, Any]]:
	"""Verify the LUKS header has been removed from the target device."""
	command = ["cryptsetup", "luksDump", device_path]
	if dry_run:
		return True, {"mode": "dry_run", "command": _serialize_command(command)}

	try:
		result = run_command(command, timeout=timeout, check=False)
	except (CommandRunnerError, CommandRunnerTimeout) as exc:
		raise VerificationError(f"luks header check failed: {exc}") from exc

	passed = result.returncode != 0
	details = {
		"command": _serialize_command(command),
		"returncode": result.returncode,
		"stdout": (result.stdout or "").strip(),
		"stderr": (result.stderr or "").strip(),
	}
	return passed, details


def check_filesystem_signatures_absent(
	device_path: str,
	dry_run: bool = False,
	timeout: int = 10,
) -> tuple[bool, dict[str, Any]]:
	"""Verify wipefs reports no residual filesystem signatures."""
	command = ["wipefs", "--list", device_path]
	if dry_run:
		return True, {"mode": "dry_run", "command": _serialize_command(command)}

	try:
		result = run_command(command, timeout=timeout, check=False)
	except (CommandRunnerError, CommandRunnerTimeout) as exc:
		raise VerificationError(f"signature check failed: {exc}") from exc

	output = (result.stdout or "").strip()
	passed = not output
	details = {
		"command": _serialize_command(command),
		"returncode": result.returncode,
		"signatures_output": output,
		"stderr": (result.stderr or "").strip(),
	}
	return passed, details


def check_random_sector_sampling(
	drive: Any,
	sample_ratio: float,
	dry_run: bool = False,
	block_size: int = 4096,
) -> tuple[bool, dict[str, Any]]:
	"""Sample sectors from the raw device to collect additional evidence.

	For HDDs, sampled sectors must be all-zero after the final fillzero pass.
	For SSD/cryptographic wipes, sector sampling is informational and succeeds
	when sampling completes without I/O errors.
	"""
	device_path = _resolve_device_path(drive)
	if dry_run:
		return True, {
			"mode": "dry_run",
			"device_path": device_path,
			"sample_ratio": sample_ratio,
			"block_size": block_size,
		}

	size_bytes = _resolve_device_size_bytes(drive)
	if size_bytes <= 0:
		raise VerificationError(f"unable to determine device size for sampling: {device_path}")

	sample_count = _compute_sample_count(size_bytes, sample_ratio)
	offsets = _build_sample_offsets(size_bytes, sample_count, block_size)
	if not offsets:
		raise VerificationError(f"unable to build sample offsets for device: {device_path}")

	is_hdd = _is_hdd_drive(drive)
	all_samples_zero = True
	samples: list[dict[str, Any]] = []

	try:
		with open(device_path, "rb") as device_file:
			for offset in offsets:
				device_file.seek(offset)
				data = device_file.read(block_size)
				if not data:
					raise VerificationError(f"no data read during sector sampling at offset {offset}")

				sample_is_zero = data == (b"\x00" * len(data))
				all_samples_zero = all_samples_zero and sample_is_zero
				samples.append(
					{
						"offset": offset,
						"bytes_read": len(data),
						"is_all_zero": sample_is_zero,
					}
				)
	except OSError as exc:
		raise VerificationError(f"sector sampling failed for {device_path}: {exc}") from exc

	passed = all_samples_zero if is_hdd else True
	details = {
		"device_path": device_path,
		"sample_ratio": sample_ratio,
		"sample_count": len(samples),
		"block_size": block_size,
		"all_samples_zero": all_samples_zero,
		"expectation": "zeroed" if is_hdd else "informational",
		"samples": samples,
	}
	return passed, details


def verify_wipe(
	drive: Any,
	app_config: Any,
	dry_run: bool = False,
	smart_before: dict[str, Any] | None = None,
) -> VerificationResult:
	"""Run post-wipe verification checks and aggregate the outcome."""
	verification_config = getattr(app_config, "verification", object())
	if not getattr(verification_config, "enabled", True):
		return VerificationResult(
			status="not_run",
			verification_errors=["verification disabled by configuration"],
			smart_before=smart_before,
		)

	device_path = _resolve_device_path(drive)
	result = VerificationResult(status="dry_run" if dry_run else "passed", smart_before=smart_before)

	checks = [
		("luks_header_destroyed", lambda: check_luks_header_destroyed(device_path, dry_run=dry_run)),
		(
			"filesystem_signatures_absent",
			lambda: check_filesystem_signatures_absent(device_path, dry_run=dry_run),
		),
		(
			"random_sector_sampling",
			lambda: check_random_sector_sampling(
				drive,
				sample_ratio=float(getattr(verification_config, "sample_ratio", 0.05)),
				dry_run=dry_run,
			),
		),
	]

	for check_name, check_func in checks:
		try:
			passed, details = check_func()
		except VerificationError as exc:
			message = f"{check_name}: {exc}"
			result.checks_failed.append(check_name)
			result.verification_errors.append(message)
			result.check_details[check_name] = {"error": str(exc)}
			log_error(f"Verification failed drive={device_path} check={check_name} error={exc}")
			continue

		result.check_details[check_name] = details
		if passed:
			result.checks_passed.append(check_name)
			log_info(f"Verification passed drive={device_path} check={check_name}")
		else:
			result.checks_failed.append(check_name)
			log_error(f"Verification failed drive={device_path} check={check_name}")

	smart_checks_enabled = bool(getattr(verification_config, "smart_checks_enabled", True))
	if smart_checks_enabled:
		if is_smartctl_available():
			try:
				result.smart_after = collect_smart_info(device_path)
				result.check_details["smart_snapshot"] = {
					"before_available": smart_before is not None,
					"after_available": result.smart_after is not None,
				}
			except SmartctlError as exc:
				message = f"smart_snapshot: {exc}"
				result.verification_errors.append(message)
				result.check_details["smart_snapshot"] = {"error": str(exc)}
				log_error(f"SMART verification error drive={device_path} error={exc}")
		else:
			result.verification_errors.append("smart_snapshot: smartctl unavailable")
			result.check_details["smart_snapshot"] = {"error": "smartctl unavailable"}

	if dry_run:
		result.status = "dry_run"
	elif result.checks_failed:
		result.status = "failed"
	else:
		result.status = "passed"

	return result
