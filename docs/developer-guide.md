# Secure-Wipe Developer Guide

## Purpose
This guide documents module responsibilities, development workflow, test strategy, and release validation expectations for Secure-Wipe contributors.

## Architecture Map
- `app/main.py`: top-level orchestration and menu dispatch.
- `app/modules/config.py`: config loading, validation, and persisted user-facing settings writes.
- `app/modules/menu_shell.py`: top-level menu rendering and status summary.
- `app/modules/drive_detection.py`: detection, normalization, safety filtering, and drive selection workflow.
- `app/modules/wipe_engine.py`: wipe execution orchestration and recovery-aware step tracking.
- `app/modules/recovery.py`: lock management, persisted state lifecycle, and resume eligibility.
- `app/modules/verification.py`: post-wipe validation checks.
- `app/modules/reporting.py`: detection and wipe report serialization and file persistence.
- `app/modules/uploader.py`: queued upload logic and retry behavior.
- `app/modules/app_logging.py`: file-based logging setup and write helpers.
- `app/modules/terminal.py`: command runner and terminal utility primitives.

## Branching Strategy
- Primary stable branch: `main`
- Feature branches: one concern per branch, for example:
  - `feature/hardening-logging-and-errors`
  - `feature/hardening-resume-and-recovery-ops`
  - `docs/readme-runbooks-refresh`
- Merge policy: PR into `main` with tests passing before merge.

## Local Development Workflow
1. Sync branch from `main`.
2. Implement scoped changes.
3. Run targeted tests for touched modules.
4. Run full test suite.
5. Update docs when behavior changes.
6. Open PR to `dev` with test evidence.

## Test Strategy
### Unit Tests
- Framework: Python `unittest` and `unittest.mock`.
- Scope: module behavior and error-path resilience.

### Commands
- Full suite:
  - `PYTHONPATH=.:./app python3 -m unittest discover -s app -p 'test_*.py' -v`
- Targeted suites:
  - `PYTHONPATH=.:./app python3 -m unittest app.tests.test_app_logging -v`
  - `PYTHONPATH=.:./app python3 -m unittest app.tests.test_util_and_main -v`

## Menu and UX Notes
- Top-level menu actions are defined in `modules/menu_shell.py`.
- Submenu rendering and navigation rules are shared between `main.py` and `modules/menu_shell.py`.
- Main menu input accepts numeric options only.
- Submenu return key: `R`.
- Report viewer pagination defaults to 20 entries per page with `N`/`P` navigation.
- Log viewer pagination defaults to 20 entries per page with `N`/`P` navigation.
- Current top-level actions include Start Job, Restart Pending Jobs, View Reports, View Logs, Configuration, Maintenance, Open Terminal, Shutdown System, and Restart System.

## Configuration Notes
- User-facing keys are a whitelisted subset in `modules/config.py`.
- In-app configuration changes are persisted through `save_user_config`.
- Runtime path behavior:
  - `dev`: `/app/...` defaults (container-first)
  - `prod`: repository-local directories (`logs`, `reports`, `state`, `tmp`)

### User-Facing Configuration Matrix

The keys below are accepted from `configuration.toml`; unknown keys are rejected.

| Table | Keys |
|-------|------|
| `paths` | `output_root` |
| `runtime` | `environment`, `dry_run`, `timezone` |
| `safety` | `removable_drive_mode`, `mount_handling_mode`, `confirmation_steps` |
| `drive_detection` | `collect_smart_info` |
| `recovery` | `checkpoint_interval_seconds`, `max_resume_attempts`, `lock_file_path`, `lock_stale_seconds`, `resume_state_max_age_seconds`, `allow_failed_resume` |
| `wipe` | `container_scrub_pattern`, `hdd_final_scrub_pattern` |
| `reporting` | `formats`, `detail_level`, `operator_identifier` |
| `upload` | `enabled`, `repo`, `branch`, `retry_count`, `ssh_private_key_path` |
| `logging` | `enabled`, `level` |

### Reporting Detail-Level Behavior

| Detail Level | JSON Output | Text Output | Notes |
|-------------|-------------|-------------|-------|
| `minimal` | High-level run status and basic drive identity | Compact status-oriented sections | Best for quick operational checks |
| `standard` | Includes wipe method and verification check names (`checks_passed`, `checks_failed`) | Includes passed/failed check name lists | Default troubleshooting view |
| `verbose` | Adds step timings, verification errors, and full recovery details | Adds timeline and deep diagnostics | Preferred for incident analysis |

### Verification Check Names

Post-wipe verification currently executes three checks in sequence:
- `luks_header_destroyed`
- `filesystem_signatures_absent`
- `random_sector_sampling`

If operator output says for example "2 passed, 1 failed", the failed check name is now present in standard and verbose reports.

## Hardening Checklist for Contributors
- Avoid silent failure paths.
- Emit clear operator-facing error messages.
- Preserve recovery state correctness on partial failure.
- Add regression tests for every bug fix.
- Keep destructive defaults safe (`dry_run = true` unless explicit validation path is being exercised).

## Release Validation Expectations
1. Full unit test suite passes.
2. Menu/report/config workflows validated interactively.
3. Recovery lock/state behavior validated in failure scenarios.
4. Controlled non-dry-run validation completed on approved hardware.
5. Evidence captured in logs and reports for release notes.
