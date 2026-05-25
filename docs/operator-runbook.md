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
4. Select one of the top-level menu actions:
	 - Start Job
	 - Restart Pending Jobs
	 - View Reports
	 - Configuration
5. Complete confirmation prompts for destructive operations.
6. Wait for wipe + verification completion.
7. Confirm report output paths displayed by the application.
8. Archive or upload reports per environment policy.

## Submenu Controls
- `B` or `R`: Return to the main menu from any submenu.
- Report viewer keys:
	- Number: Open selected report from current page
	- `N` or `F`: Next report page
	- `P`: Previous report page
	- `B` or `R`: Return to main menu

Drive selection keys:
- Number or comma-separated numbers: select drives
- `N` or `F`: Next drive page
- `P`: Previous drive page
- `B`, `R`, or `Q`: return without selecting drives

Report viewer pagination shows up to 20 report files per page.

## Configuration Submenu Actions
The Configuration submenu currently supports:
- Toggle dry run mode
- Toggle upload enabled mode
- Toggle SMART collection
- Toggle logging level (`info`/`errors`)
- Cycle reporting detail level (`minimal`/`standard`/`verbose`)
- Cycle container scrub pattern (for encrypted container write stage)
- Cycle HDD final scrub pattern (for direct-device final HDD pass)

Configuration updates are persisted to `configuration.toml` after each successful change.

## Configuration Options Quick Reference

| Table | Key | Recommended Baseline | Operator Impact |
|-------|-----|----------------------|-----------------|
| `runtime` | `dry_run` | `true` for rehearsal, `false` only for approved destructive run | Controls whether wipes are simulated or real |
| `runtime` | `timezone` | site timezone, for example `America/Edmonton` | Affects time display and output naming behavior |
| `safety` | `confirmation_steps` | `2` | Additional destructive-operation confirmation prompts |
| `wipe` | `container_scrub_pattern` | `fillzero` | Pattern used during encrypted container overwrite |
| `wipe` | `hdd_final_scrub_pattern` | `fillzero` | Pattern used for final HDD pass |
| `reporting` | `detail_level` | `standard` for normal operations | Controls report depth and visibility of check names |
| `upload` | `enabled` | `false` unless remote is validated | Enables queued Git report upload flow |
| `upload` | `ssh_private_key_path` | empty unless SSH auth needed | Path to SSH key for Git operations |

## Reporting Levels (What Changes)

| Level | What You See | Best Use |
|------|---------------|----------|
| `minimal` | Core status only, no detailed check breakdown | High-level pass/fail monitoring |
| `standard` | Wipe method, verification counts, and check names (passed/failed) | Day-to-day operator workflow |
| `verbose` | Full detail including timelines and verification error payloads | Failure triage and deep diagnostics |

### Example: Verification 2 Passed / 1 Failed

With `reporting.detail_level = standard`, report output will show both counts and names under:
- `Passed Checks`
- `Failed Checks`

Typical check names are:
- `luks_header_destroyed`
- `filesystem_signatures_absent`
- `random_sector_sampling`

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

If `upload.ssh_private_key_path` is set, Git uses that key for SSH auth.

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
