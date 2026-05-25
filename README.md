# SecureWipe

A secure drive sanitization system for IT asset disposition workflows.

SecureWipe is a terminal-first workflow that detects candidate drives, applies a cryptographic wipe sequence, validates the result with post-wipe checks, and writes auditable artifacts (logs, JSON report, text report) for chain-of-custody and troubleshooting.

## System Overview

SecureWipe is designed to be safe-by-default and operator-friendly:
- Strong guardrails before destructive actions (drive filtering + confirmations)
- Recovery-aware execution with lock/state handling for interruption scenarios
- Verification checks that report both counts and check names in standard/verbose reports
- Configurable wipe patterns and reporting depth
- Optional queued Git upload for report archival

## What's Done

- ✅ Configuration loading and validation (`configuration.toml` + `modules/config.py`)
- ✅ Drive detection, normalization, safety filtering, and user confirmation flow
- ✅ Wipe engine orchestration (LUKS2 workflow, scrub, signature cleanup, HDD final zero pass)
- ✅ Recovery checkpointing, resume logic, stale lock handling, and state lifecycle
- ✅ Verification checks (LUKS header, residual signatures, random sector sampling, SMART snapshot)
- ✅ Report generation (JSON + text) with detail-level controls
- ✅ Git-based upload queue with retry/backoff and local retention semantics
- ✅ Daily file logging and centralized terminal command runner utilities
- ✅ In-app report viewing submenu with pagination and keyboard navigation (`R` return, `N` next page, `P` previous page)
- ✅ In-app configuration submenu for controlled runtime toggle updates with persisted settings
- ✅ Comprehensive unit test suite (`unittest`, mocked destructive operations)

## What's Next

**Immediate Priorities:**
1. Harden error taxonomy and user-facing failure messages across modules
2. Expand integration and fault-injection scenarios (timeouts, partial failures, network issues)
3. Perform controlled non-dry-run validation on approved hardware
4. Finalize operator documentation and known-limits documentation

## Menu Navigation

Top-level actions now include:
- Start Job
- Restart Pending Jobs
- View Reports
- Configuration

Submenu behavior:
- `B` or `R` returns to the previous menu
- Report viewer shows up to 20 entries per page
- Report viewer supports `N`/`F` for next page and `P` for previous page

Drive selection behavior:
- `N`/`F` for next page and `P` for previous page (when multiple pages are present)
- `B`/`R`/`Q` returns without selecting drives
- Comma-separated drive numbers select one or more drives

## Configuration Reference

SecureWipe only accepts a curated set of keys in `configuration.toml`. Unknown keys fail validation at startup.

### Runtime and Safety

| Table | Key | Values | What It Controls |
|-------|-----|--------|------------------|
| `paths` | `output_root` | path or empty | Optional writable root used in `prod` for logs/reports/state. |
| `runtime` | `environment` | `dev`, `test`, `prod` | Runtime mode; `prod` remaps runtime artifact directories. |
| `runtime` | `dry_run` | `true`, `false` | If `true`, destructive commands are simulated. |
| `runtime` | `timezone` | `UTC`, `local`, IANA zone | Timezone used for output naming/time behavior. |
| `safety` | `removable_drive_mode` | `deny`, `allow` | Whether removable drives are eligible for wipe selection. |
| `safety` | `mount_handling_mode` | `deny`, `allow` | Whether mounted drives are blocked or allowed. |
| `safety` | `confirmation_steps` | `0`, `1`, `2` | Confirmation strictness before destructive execution. |

### Wipe, Verification, and Reporting

| Table | Key | Values | What It Controls |
|-------|-----|--------|------------------|
| `drive_detection` | `collect_smart_info` | `true`, `false` | Captures SMART metadata during detection when available. |
| `wipe` | `container_scrub_pattern` | scrub pattern (for example `fillzero`, `nnsa`) | Pattern used for encrypted-container overwrite stage. |
| `wipe` | `hdd_final_scrub_pattern` | scrub pattern (for example `fillzero`, `dod`) | Pattern used in the direct-device final HDD pass. |
| `reporting` | `formats` | any of `json`, `txt` | Report output formats to persist. |
| `reporting` | `detail_level` | `minimal`, `standard`, `verbose` | Report payload depth for JSON and text outputs. |
| `logging` | `enabled` | `true`, `false` | Enables/disables application log writes. |
| `logging` | `level` | `info`, `errors` | Log verbosity threshold. |

### Recovery and Upload

| Table | Key | Values | What It Controls |
|-------|-----|--------|------------------|
| `recovery` | `checkpoint_interval_seconds` | integer > 0 | Checkpoint cadence for long wipe steps. |
| `recovery` | `max_resume_attempts` | integer >= 0 | Resume retry ceiling before forcing restart path. |
| `recovery` | `lock_file_path` | path | Lock file location guarding concurrent wipes. |
| `recovery` | `lock_stale_seconds` | integer > 0 | Age threshold for stale-lock logic. |
| `recovery` | `resume_state_max_age_seconds` | integer > 0 | Maximum age for resume-eligible recovery states. |
| `recovery` | `allow_failed_resume` | `true`, `false` | If `true`, failed states may still be offered for resume. |
| `upload` | `enabled` | `true`, `false` | Enables Git-based report upload queue/push flow. |
| `upload` | `repo` | Git URL | Target remote repository URL. |
| `upload` | `branch` | branch name | Target branch for report commits. |
| `upload` | `retry_count` | integer > 0 | Push retry attempts with backoff. |
| `upload` | `ssh_private_key_path` | path or empty | Optional SSH private key path used via `GIT_SSH_COMMAND`. |

## Reporting Detail Levels

`reporting.detail_level` controls both JSON and text report depth.

| Level | Includes | Omits | Typical Use |
|------|----------|-------|-------------|
| `minimal` | status, basic drive identity/path, timestamps, high-level verification status | wipe method details, platform metadata, step timeline, verification check names | Fast operator confirmation and dashboards |
| `standard` | machine/drive metadata, wipe method, verification counts and verification check names (passed/failed), recovery summary | per-step duration timeline, verbose verification error lists | Normal production operations and troubleshooting |
| `verbose` | everything in standard plus step durations, detailed verification lists/errors, full recovery session details | none (full payload) | Deep incident analysis and engineering diagnostics |

## Verification Checks Reference

| Check Name | What Pass Means | Common Failure Cause |
|-----------|-----------------|----------------------|
| `luks_header_destroyed` | LUKS metadata is no longer readable on target device. | Header erase step failed or wrong target path inspected. |
| `filesystem_signatures_absent` | `wipefs --list` returns no residual signatures. | Residual filesystem signatures remain. |
| `random_sector_sampling` | Sampling completed (SSD/NVMe) or sampled sectors are all-zero (HDD expectation). | HDD final pass pattern not zeroing (for example `nnsa`/`dod`), or read/I/O sampling issues. |

## Project Overview

SecureWipe is designed for secure decommissioning workflows. It:
- Boots from USB on Windows enterprise hardware
- Detects SATA/NVMe/USB storage devices
- Performs cryptographic wipe using LUKS2/dm-crypt
- Verifies wipe completion with forensic checks
- Generates audit reports and uploads to Git
- Recovers gracefully from interruptions

### Key Features
- Selective drive targeting with safety confirmations
- SMART data collection before/after wipe
- State persistence for recovery handling
- Structured JSON + text reporting
- Git-based audit trail

## Quick Start

### Prerequisites
- Windows with WSL2
- Docker Desktop installed
- SSH key configured for GitHub (see Setup section)

### Development Environment Setup

1. **Clone and enter project**
   ```bash
   cd /home/mbehrens/projects/Secure-Wipe
   ```

2. **Build Docker image** (one-time, ~30-60 seconds)
   ```bash
   docker compose build
   ```

3. **Start development container**
   ```bash
   docker compose run --rm securewipe bash
   ```

4. **Verify environment inside container**
   ```bash
   python3 --version           # Should show Python 3.11+
   cryptsetup --version        # Should show cryptsetup version
   smartctl --version          # Should show smartmontools version
   ls -la modules/             # Should show all module files
   ```

### Edit Code & Run

Edit Python files in VS Code on Windows — changes sync instantly to container:

```bash
# In container, from /app
python3 main.py                     # Run the application
python3 -m unittest discover -s tests -v   # Run the full unit test suite
python3 run_tests.py                        # Alternate test runner
python3 -c "from modules import config"  # Test imports
```

### Container Workflow

**Option 1: Interactive development**
```bash
docker compose run --rm securewipe bash
# Inside container, edit and test as needed
```

**Option 2: Direct command execution**
```bash
# From host terminal
docker compose exec securewipe python3 main.py
```

**Option 3: Background container**
```bash
docker compose up -d           # Start in background
docker compose exec securewipe bash  # Connect to it
docker compose down            # Stop when done
```

## Architecture

```
securewipe/
├── main.py                      # Entry point, CLI orchestration
├── modules/
│   ├── __init__.py              # Package initialization
│   ├── config.py                # Configuration & settings
│   ├── drive_detection.py       # Hardware enumeration (lsblk, smartctl)
│   ├── wipe_engine.py           # LUKS2 cryptographic wipe workflow
│   ├── recovery.py              # State management & resumption
│   ├── verification.py          # Post-wipe validation checks
│   ├── reporting.py             # JSON + text report generation
│   └── uploader.py              # Git repository upload logic
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Linux environment (Debian 12)
├── docker-compose.yml           # Container orchestration
├── .dockerignore                # Build context exclusions
├── logs/                        # Execution logs
├── reports/                     # Generated wipe reports
└── state/                       # Operation state files (JSON)
```

## Current Focus Checklist

Before release hardening sign-off, confirm:

- [x] Core modules implemented (`config`, `drive_detection`, `wipe_engine`, `recovery`, `verification`, `reporting`, `uploader`)
- [x] End-to-end orchestration in `main.py`
- [x] Unit test suite passing locally (`python3 -m unittest discover -s tests -v`)
- [x] Dry-run default enabled in `configuration.toml`
- [x] Upload default disabled until repository target is configured
- [ ] Controlled non-dry-run execution validated on approved test hardware
- [x] Operator runbook finalized for incident handling and retries
- [x] Hard-failure playbook documented (power loss, lock contention, corrupted state, upload outages)

## Operational Documentation

- Operator runbook: `docs/operator-runbook.md`
- Hard-failure playbook: `docs/hard-failure-playbook.md`

## Git Workflow

### Branch Strategy

```
main (production-stable)
  └── dev (integration)
      ├── feature/config-setup
      ├── feature/drive-detection
      ├── feature/wipe-engine
      └── ... (other features)
```

### Daily Workflow

1. **Create feature branch from dev:**
   ```bash
   git switch dev
   git switch -c feature/your-feature-name
   ```

2. **Make changes and commit:**
   ```bash
   git add .
   git commit -m "Add feature description"
   ```

3. **Push to GitHub:**
   ```bash
   git push -u origin feature/your-feature-name
   ```

4. **When feature is ready:**
   - Create PR: feature → dev
   - Review and merge
   - Delete feature branch

5. **When dev is stable:**
   - Create PR: dev → main
   - This becomes a release point

### Commit Message Convention

```
feature: Add drive detection module
fix: Resolve permission error in wipe engine
docs: Refresh README operational guidance
chore: Update requirements.txt with new dependency
```

## Testing Strategy

### Unit Tests
- Test individual module functions
- Mock system calls (lsblk, cryptsetup, etc.)
- No privileged operations needed

### Integration Tests
- Test module interactions
- Mock loop devices for drive simulation
- Run in Docker container

### Hardware Validation
- Real drive detection on actual hardware
- SMART data collection
- Runs outside Docker (direct hardware access)

## Setup & Configuration

### GitHub SSH Key Setup (for repo access)

```bash
# In WSL2 terminal
ssh-keygen -t ed25519 -C "your_email@example.com"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# Copy and paste public key to GitHub Settings → SSH Keys
cat ~/.ssh/id_ed25519.pub

# Verify connection
ssh -T git@github.com
```

### Git Configuration

```bash
git config --global user.name "Your Name"
git config --global user.email "your_email@example.com"
```

## Key Design Decisions

| Aspect | Choice | Reason |
|--------|--------|--------|
| **Base Image** | Debian 12 | Matches production, stable, minimal footprint |
| **Python Environment** | System Python in container | Simpler than venv in container; Docker is the isolation boundary |
| **Project Structure** | modules/ package | Cleaner organization, easier imports, scales better |
| **Dependency Management** | pip + requirements.txt | Standard, reproducible, easy to track |
| **Wipe Method** | LUKS2 + dd | Industry standard, forensically defensible |
| **State Management** | JSON files in state/ | Simple, auditable, human-readable, recoverable |
| **Reporting** | JSON + text formats | Structured data + human-readable audit trail |
| **Logging** | Python logging module | Consistent, structured, production-ready |

## Out of Scope

- Custom Linux distributions
- Secure Boot signing
- Enterprise authentication
- Multiple upload backends
- Graphical desktop UI
- Parallel drive wiping
- Cloud orchestration
- CI/CD infrastructure

## Known Limitations

- Real destructive validation is environment-dependent and should only be executed on approved test media.
- Upload workflow currently targets a single Git remote and branch per configuration.
- No GUI is provided; operation is terminal-driven by design.
- Parallel drive wiping is intentionally out of scope.

## Runtime Path Notes

- In `dev`, default paths are `/app/...` and are intended for container execution.
- In `prod`, runtime directories are remapped to repository-local paths (`logs`, `reports`, `state`, `tmp`) so host execution is supported.

## Troubleshooting

### Docker build fails
```bash
docker compose down
docker system prune
docker compose build --no-cache
```

### Container won't start
```bash
docker compose logs securewipe
```

### SSH access issues
```bash
ssh-add ~/.ssh/id_ed25519
eval "$(ssh-agent -s)"
ssh -T git@github.com
```

## Contributing

1. Create feature branch from `dev`
2. Implement changes
3. Test thoroughly (unit + integration)
4. Commit with clear messages
5. Create PR to `dev`
6. Code review + merge

## Learning Outcomes

By completing this project, you'll demonstrate:
- Systems-level Linux programming (Python)
- Cryptographic workflows (LUKS2/dm-crypt)
- Low-level storage technologies (SATA, NVMe, USB)
- Safe destructive operation design
- Interruption recovery and state management
- Structured logging and audit trails
- Git-based operational reporting
- Maintainable systems administration tooling

## Resources

- [cryptsetup Documentation](https://gitlab.com/cryptsetup/cryptsetup)
- [smartmontools User Guide](https://www.smartmontools.org/)
- [Linux Storage Stack](https://en.wikipedia.org/wiki/Linux_kernel#Storage)
- [LUKS2 Specification](https://gitlab.com/cryptsetup/cryptsetup/-/wikis/LUKS-standard)

## License

(To be determined)

## Author

Matthew Behrens

---

**Last Updated:** May 2026