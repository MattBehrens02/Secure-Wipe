# SecureWipe Developer Guide

## Purpose
This guide documents module responsibilities, development workflow, test strategy, and release validation expectations for SecureWipe contributors.

## Architecture Map
- `main.py`: top-level orchestration and menu dispatch.
- `modules/config.py`: config loading, validation, and persisted user-facing settings writes.
- `modules/menu_shell.py`: top-level menu rendering and status summary.
- `modules/drive_detection.py`: detection, normalization, safety filtering, and drive selection workflow.
- `modules/wipe_engine.py`: wipe execution orchestration and recovery-aware step tracking.
- `modules/recovery.py`: lock management, persisted state lifecycle, and resume eligibility.
- `modules/verification.py`: post-wipe validation checks.
- `modules/reporting.py`: detection and wipe report serialization and file persistence.
- `modules/uploader.py`: queued upload logic and retry behavior.
- `modules/app_logging.py`: file-based logging setup and write helpers.
- `modules/terminal.py`: command runner and terminal utility primitives.

## Branching Strategy
- Base integration branch: `dev`
- Feature branches: one concern per branch, for example:
  - `feature/hardening-logging-and-errors`
  - `feature/hardening-resume-and-recovery-ops`
  - `docs/readme-runbooks-refresh`
- Merge policy: PR to `dev` with tests passing before merge.
- Release policy: PR from `dev` to `main` after validation gates are complete.

## Local Development Workflow
1. Sync branch from `dev`.
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
  - `python3 -m unittest discover -s tests -v`
- Targeted suites:
  - `python3 -m unittest tests/test_app_logging.py -v`
  - `python3 -m unittest tests/test_util_and_main.py -v`

## Menu and UX Notes
- Top-level menu actions are defined in `modules/menu_shell.py`.
- Submenu rendering and navigation rules are implemented in `main.py`.
- Submenu return key: `R`.
- Report viewer pagination defaults to 20 entries per page with `N`/`P` navigation.

## Configuration Notes
- User-facing keys are a whitelisted subset in `modules/config.py`.
- In-app configuration changes are persisted through `save_user_config`.
- Runtime path behavior:
  - `dev`: `/app/...` defaults (container-first)
  - `prod`: repository-local directories (`logs`, `reports`, `state`, `tmp`)

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
