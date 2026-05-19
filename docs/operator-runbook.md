# SecureWipe Operator Runbook

## Purpose
This runbook describes the standard operator workflow for SecureWipe in both dry-run and controlled live-run modes.

## Scope
- Single-host operation from the project workspace.
- Terminal-based usage only.
- Safe destructive-operation workflow with explicit confirmations.

## Goal Alignment
This procedure directly supports practicum goals in `goal.txt`:
- Safe selective drive targeting
- Cryptographic wipe workflow execution
- Verification and reporting
- Recovery from interruptions
- Repeatable operational reliability

## Pre-Run Safety Requirements
- Confirm you are on approved test hardware/media.
- Confirm target drives are decommissioning candidates.
- Confirm boot media/system disk is not selected.
- Confirm you have permission to perform destructive testing.

## Runtime Modes
### Dry Run (default)
- `configuration.toml` sets `runtime.dry_run = true`.
- Commands are simulated.
- Reports and logs are still produced.

### Controlled Live Run
- Set `runtime.dry_run = false` only for approved validation.
- Keep `upload.enabled = false` unless upload target is configured and tested.

## Environment Notes
SecureWipe is commonly run in a container where `/app` paths are valid.
If running from host/venv, ensure configured runtime directories are writable (`logs`, `reports`, `state`, `tmp`).

## Standard Operation Procedure
1. Start in the project root.
2. Verify configuration values in `configuration.toml`.
3. Run SecureWipe.
4. Select drive(s) from presented menu.
5. Complete confirmation prompts.
6. Wait for wipe + verification completion.
7. Confirm report output paths displayed by the application.
8. Archive or upload reports per environment policy.

## Command Reference
### Run application
```bash
python3 main.py
```

### Run test suite before or after changes
```bash
python3 -m unittest discover -s tests -v
```

### Alternate test entrypoint
```bash
python3 run_tests.py
```

## Expected Artifacts
- Logs: `logs/YYYY-MM-DD.log`
- Reports (JSON and text): `reports/YYYYMMDDTHHMM-device-serial.{json,txt}`
- Recovery state files: `state/*.state.json`
- Recovery lock file (runtime): `state/wipe.lock`

## Recovery/Resume Behavior
On startup, SecureWipe checks for resumable states.
Operator choices:
- Resume incomplete wipe
- Start fresh and clear resumable states

Recommended practice:
- Resume if interruption was environmental (power/network/process interruption).
- Start fresh if prior state indicates repeated deterministic failure.

## Upload Behavior
If `upload.enabled = true` and repo configuration is valid:
- Reports are queued and committed to local upload repo clone.
- Push uses retries/backoff.
- Failed pushes keep reports queued locally for later retry.

Upload internals:
- Queue file: `state/.upload_queue`
- Local upload clone: `.upload_repo/`

## Operator Completion Checklist
- [ ] Confirmed target devices before execution
- [ ] Confirmed run mode (`dry_run` vs live)
- [ ] Confirmed verification status in terminal output
- [ ] Confirmed report files exist in `reports/`
- [ ] Reviewed `logs/YYYY-MM-DD.log` for errors/warnings
- [ ] Recorded session metadata (operator, machine, test notes)

## Escalation Criteria
Stop and escalate to maintainer when:
- Repeated failure at same wipe step across multiple runs
- Recovery resume attempts exhausted
- Verification failures persist on known-good test media
- Directory/permission issues prevent artifact generation
