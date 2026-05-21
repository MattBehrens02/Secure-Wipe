# SecureWipe

A bootable drive sanitization utility for secure IT asset disposition. Wipes connected storage devices using cryptographic methods with full audit logging and recovery handling.

## Project Status

**Phase:** Pre-Hardening - Core Workflow Implemented

| Phase | Status | Est. Hours |
|-------|--------|-----------|
| Docker & Project Setup | ✅ Complete | ~4h |
| Phase 1: Drive Detection + CLI | ✅ Complete | ~15h |
| Phase 2: Wipe Engine + Recovery | ✅ Complete | ~35h |
| Phase 3: Verification + Reporting + Upload | ✅ Complete | ~25h |
| Phase 4: Hardening & Validation | 🔄 Next Focus | ~15h |

**Total Estimated Timeline:** ~100 development hours

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

**Immediate (Phase 4 - Hardening):**
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
- `R` returns to main menu
- Report viewer shows up to 20 entries per page
- Report viewer supports `N` and `P` for page navigation

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

## Development Phases

### Phase 1: Foundation (~15h) — COMPLETE
**Goal:** Drive detection + CLI infrastructure

**Build Order:**
1. `modules/config.py` — Configuration structure & logging setup
2. `modules/drive_detection.py` — Hardware enumeration (lsblk, smartctl parsing)
3. `main.py` — CLI menu, drive selection, confirmation prompts

**Deliverables:**
- Working drive detection and metadata collection
- CLI menu for safe drive selection
- Test on real hardware validates approach

### Phase 2: Wipe Engine + Recovery (~35h) — COMPLETE
**Goal:** Functional cryptographic wipe with resumable state

**Build Order:**
1. `modules/wipe_engine.py` — LUKS2 orchestration, HDD overwrite
2. `modules/recovery.py` — State tracking, interruption recovery

**Deliverables:**
- Full wipe workflow (encryption → write → verification)
- State persistence for incomplete operations
- Resumption logic

### Phase 3: Verification, Reporting, and Upload (~25h) — COMPLETE
**Goal:** Post-wipe validation & audit trail

**Build Order:**
1. `modules/verification.py` — Header removal, SMART checks
2. `modules/reporting.py` — JSON + text report generation
3. `modules/uploader.py` — Git repository integration

**Deliverables:**
- Comprehensive post-wipe validation
- Structured audit reports
- Git-based operational traceability

### Phase 4: Hardening (~15h) — IN PROGRESS
**Goal:** Error handling, edge cases, stability

- Comprehensive error handling (all modules)
- Interruption recovery workflows
- Edge case testing
- Documentation finalization and runbook polish

## Hardening Readiness Checklist

Before moving from `dev` toward release hardening, confirm:

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
docs: Update README with phase 1 status
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
- Dedicated operator maintenance commands for stale lock/state cleanup are not yet implemented.

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

Matt Behrens

---

**Last Updated:** May 2026