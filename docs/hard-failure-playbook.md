# SecureWipe Hard-Failure Playbook

## Purpose
This playbook provides incident response procedures for hard failures during detection, wipe, verification, recovery, and upload flows.

## Incident Severity
- SEV-1: Potential wrong-drive risk, data safety concern, or unknown device targeting behavior.
- SEV-2: Wipe/verification failure with no wrong-drive risk.
- SEV-3: Reporting/upload/logging failure with successful wipe and verification.

## Immediate Response Rules
1. Stop additional wipe operations.
2. Preserve logs and reports before modifying state.
3. Do not manually run destructive commands outside SecureWipe unless explicitly required.
4. Capture exact error text and timestamp.

## Failure Scenario: Permission or Path Errors
### Symptoms
- `PermissionError` creating runtime directories (for example `/app/...`).

### Actions
1. Confirm execution context (container vs host/venv).
2. Validate configured runtime paths are writable.
3. Re-run after correcting path permissions or environment.
4. Record incident with failing path and environment details.

## Failure Scenario: No Drives Detected
### Symptoms
- Application reports no eligible drives.

### Actions
1. Confirm physical connection and power state of test drives.
2. Confirm safety policy settings are not excluding intended devices.
3. Validate required tooling availability (`lsblk`, optional `smartctl`).
4. Re-run and compare with prior log timestamps.

## Failure Scenario: Wipe Step Failure
### Symptoms
- Result status `failed` with `failed_step` and error message.

### Actions
1. Record `failed_step` and `error_message` from terminal/report.
2. Check `logs/YYYY-MM-DD.log` for command context.
3. If state exists, decide resume vs restart policy:
   - Resume for interruption-like events.
   - Restart for deterministic repeated command failures.
4. Validate cleanup artifacts:
   - Mapper closure state
   - Temporary key cleanup behavior
5. Run only one retest after corrective change; avoid repeated blind retries.

## Failure Scenario: Recovery Lock Contention
### Symptoms
- Startup reports lock acquisition failure (`wipe.lock`).

### Actions
1. Confirm no active SecureWipe process is running.
2. If stale lock is suspected, wait for stale-threshold policy to expire and retry.
3. Note: there is currently no dedicated operator cleanup command for stale lock/state maintenance.
4. Use maintainer-approved manual cleanup only after evidence capture.
5. Re-run and document lock metadata and elapsed age.

### Interim Manual Cleanup (Maintainer-Only)
Use only when the process is confirmed inactive and evidence has been captured.

```bash
# Inspect lock and state artifacts
ls -la state

# Remove stale lock file (if confirmed stale and no active process)
rm -f state/wipe.lock

# Remove a specific stale recovery state for a drive token (example)
rm -f state/dev_sda.state.json
```

Record every manual deletion in incident notes.

### Future Work
- Add explicit maintenance commands for stale lock/state cleanup.
- Add guarded confirmation prompts and dry-run support for maintenance operations.
3. Re-run and document lock metadata and elapsed age.

## Failure Scenario: Corrupted Recovery State
### Symptoms
- Resume not offered when expected, or malformed state behavior.

### Actions
1. Preserve `state/*.state.json` as evidence.
2. Validate JSON structure and timestamps.
3. Start fresh wipe only after evidence capture.
4. Attach state file and corresponding log excerpt to issue notes.

## Failure Scenario: Verification Failure
### Symptoms
- Verification status `failed` or specific failed checks.

### Actions
1. Identify failed check(s):
   - LUKS header removal
   - Filesystem signature absence
   - Random sector sampling
2. Confirm drive classification (HDD vs SSD/NVMe) and expected behavior.
3. Re-run in controlled conditions once.
4. Escalate if repeated failure persists on known-good media.

## Failure Scenario: Report Save Failure
### Symptoms
- Error during report generation/save.

### Actions
1. Verify `reports/` directory writability.
2. Check log entries around report serialization/save.
3. Preserve terminal output and attempt one rerun.
4. If persistent, treat as SEV-3 and file issue with traceback.

## Failure Scenario: Report Viewer Read Failure
### Symptoms
- Report viewer cannot open a selected report.
- Viewer shows read error for a report file.

### Actions
1. Capture the exact filename and error text from the viewer output.
2. Check file permissions and encoding viability of the report file.
3. Verify `reports/` directory readability and disk health.
4. If one file is corrupted, continue operations and isolate the file for analysis.
5. If repeated across files, escalate as SEV-3 and attach log excerpts.

## Failure Scenario: Configuration Write Failure
### Symptoms
- Configuration submenu reports failure while saving updates.

### Actions
1. Capture terminal output and current `configuration.toml` state.
2. Validate file permissions and parent directory writability.
3. Confirm filesystem free space and read-only mount conditions.
4. Re-run with no destructive action and verify the same toggle path.
5. Escalate as SEV-3 if persistent and include traceback/log excerpts.

## Failure Scenario: Upload Failure
### Symptoms
- Upload failed; reports retained locally.

### Actions
1. Confirm `upload.enabled`, repo URL, and branch configuration.
2. Verify network/SSH connectivity to remote.
3. Check queue file `state/.upload_queue` for pending items.
4. Confirm pending reports remain in local `reports/`.
5. Retry upload in next run window after connectivity restoration.

## Evidence Collection Template
Collect and retain:
- Timestamp (UTC)
- Hostname/environment
- Command used (`python3 main.py`)
- Full traceback or terminal error block
- Relevant log excerpt (`logs/YYYY-MM-DD.log`)
- Report files (JSON/TXT) when available
- Recovery state files (`state/*.state.json`) when present

## Recovery Decision Matrix
- Interruption/power loss with valid state: Resume preferred.
- Deterministic command error at same step: Restart after remediation.
- Unknown targeting behavior: Stop immediately and escalate (SEV-1).
- Upload-only failure with successful wipe: Continue operations; queue for later upload.

## Post-Incident Actions
1. Document root cause and corrective action.
2. Add regression tests for discovered edge case when feasible.
3. Update runbook/playbook if procedure changed.
4. Track unresolved risks in project known limitations.

## Menu Navigation Notes
- Submenus use `R` to return to the main menu.
- Report viewer pagination uses `N`/`P` for navigation and numeric selection for opening entries.
