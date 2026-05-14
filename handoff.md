# SecureWipe Agent Handoff

## Purpose
This document gives a fresh coding agent enough context to continue implementation without re-discovery.

## Project Goal
Build a bootable Linux drive sanitization tool for secure IT asset disposition:
- Detect drives safely (SATA/NVMe/USB)
- Execute cryptographic wipe workflow (LUKS2/dm-crypt)
- Verify wipe completion
- Recover from interruption
- Generate auditable reports and upload them

## Current Status (as of 2026-05-14)
- Branch: `dev`
- Core environment and project structure are in place.
- Drive detection and selection is largely implemented.
- Wipe engine and downstream phases are not yet implemented.

## What Is Implemented

### Entrypoint and orchestration
- `main.py` loads config, initializes terminal behavior, runs drive selection, and optionally writes a detection report.
- Runtime directories are ensured via `modules/dir_check.py`.
- Header is printed from `modules/header.py`.

### Configuration
- `modules/config.py` has typed dataclass config, TOML loading, key validation, and value validation.
- `configuration.toml` currently sets:
  - `runtime.environment = "prod"`
  - `runtime.dry_run = true`
  - `safety.removable_drive_mode = "deny"`
  - `safety.mount_handling_mode = "deny"`
  - `safety.confirmation_steps = 2`
  - `drive_detection.collect_smart_info = false`
  - `reporting.reports_enabled = false`

### Drive detection + selection
- `modules/drive_detection.py` currently includes:
  - `lsblk` JSON discovery
  - normalization into `Drive` dataclass
  - media type inference (`HDD`, `SSD`, `NVMe`, USB variants)
  - safety filtering for mounted/removable drives based on config
  - interactive selection UI and confirmation loop
  - multi-drive warning and high-risk warning banner
  - optional SMART enrichment when enabled

### Command execution and terminal utilities
- `modules/terminal_ui.py` currently contains both:
  - terminal helpers (`clear`, alternate screen enter/exit)
  - command execution helper (`run_command` and related error types)
- Team/user preference from current conversation:
  - Keep `subprocess` only in `modules/terminal_ui.py`

### Reporting (partial)
- `modules/reporting.py` can generate a detection JSON report with detail levels.
- Main currently only writes detection report if enabled.

## What Is Not Implemented Yet
- `modules/wipe_engine.py` (empty)
- `modules/recovery.py` (empty)
- `modules/verification.py` (empty)
- `modules/uploader.py` (empty)
- End-to-end orchestration beyond drive selection in `main.py`
- Automated tests (no substantial `tests/` coverage yet)

## Highest-Priority Next Task
Implement `modules/wipe_engine.py` happy path for a single selected drive.

### Recommended first scope
Create one function that executes cryptographic wipe steps with structured step results:
1. Preflight checks (device exists, not mounted unless policy allows)
2. Generate temporary key material
3. Create LUKS2 container on target
4. Open dm-crypt mapping
5. Fill mapped device
6. Close mapping
7. Destroy/overwrite LUKS header metadata
8. Remove residual filesystem signatures (`wipefs`)
9. If media type is HDD, do final zero pass on physical device

### Output contract recommendation
Return a structured result object/dict like:
- `device_path`
- `status` (`success`/`failed`)
- `steps` list with per-step status, timestamps, command summary, stderr excerpt
- `failure_reason` (if any)

This result shape will make recovery, verification, and reporting easier to integrate.

## Critical Safety Considerations
- Treat all operations as destructive by default.
- Never wipe mounted drives when policy is `deny`.
- Never wipe removable drives when policy is `deny`.
- Preserve explicit confirmations before destructive operations.
- Keep dry-run mode meaningful: simulate command execution and return realistic step results.
- Prefer fail-safe behavior (abort when state is ambiguous).

## Environment and Tooling Constraints
- Development often runs in WSL + Docker.
- USB passthrough/visibility in WSL can be limited.
- Mounted-drive protection can be validated now; removable-drive behavior may need later hardware validation.

## Known Design Decisions to Preserve
- Keep `subprocess` centralized in `modules/terminal_ui.py`.
- Keep typed config validation in `modules/config.py`.
- Keep terminal clear/alternate screen behavior environment-aware via `TerminalUI`.
- Avoid bypassing safety filters for convenience.

## Suggested Immediate Implementation Plan
1. Add wipe engine data structures (`WipeStepResult`, `WipeResult`).
2. Add command wrappers in wipe engine that use `run_command` from `terminal_ui`.
3. Implement happy-path function for one drive with dry-run support.
4. Integrate single-drive wipe call in `main.py` behind existing selection flow.
5. Emit minimal structured logs per step.
6. Add a lightweight simulation test path (or at least manual dry-run verification).

## Integration Milestones After Wipe Engine
1. Add `recovery.py` checkpoint file writes at each wipe step.
2. Add `verification.py` checks post-wipe.
3. Expand `reporting.py` from detection-only to full wipe run reports.
4. Implement `uploader.py` retry queue and Git upload flow.

## Quick Validation Commands
- Syntax validation:
  - `python3 -m py_compile main.py modules/*.py`
- Run application:
  - `python3 main.py`

## Notes for Incoming Agent
- Do not revert unrelated user changes.
- Keep changes narrow and incremental.
- Prioritize correctness and operator safety over speed.
