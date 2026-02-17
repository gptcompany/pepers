# Summary: Plan 32-01 — Schema Migration v3 + Docker Restart + systemd

## Status: COMPLETE

## What was done

### Task 1: Schema migration v2→v3 with UNIQUE constraint
- Added `MIGRATIONS` dict and `_run_migrations()` framework to `shared/db.py`
- Migration v3: recreates `formulas` table with `UNIQUE(paper_id, latex_hash)`
- Deduplicates existing rows during migration (keeps lowest id per group)
- Updated SCHEMA constant to include UNIQUE for fresh databases
- Verified: fresh DB gets v3, existing v2 DB migrates cleanly

### Task 2: Docker restart policies + systemd unit templates
- Docker: `restart: unless-stopped` already present on all 6 services (no change needed)
- systemd: Created 7 files in `deploy/`:
  - `rp-discovery.service` (port 8770)
  - `rp-analyzer.service` (port 8771)
  - `rp-extractor.service` (port 8772)
  - `rp-validator.service` (port 8773)
  - `rp-codegen.service` (port 8774)
  - `rp-orchestrator.service` (port 8775)
  - `rp-pipeline.target` (groups all services)
- All units: `Restart=always`, `RestartSec=5`, `WatchdogSec=60`
- Security hardening: `PrivateTmp`, `NoNewPrivileges`, `ProtectSystem=strict`

## Files modified
- `shared/db.py`: +45 LOC (MIGRATIONS dict, _run_migrations, UNIQUE in SCHEMA)
- `deploy/rp-*.service`: 6 new files
- `deploy/rp-pipeline.target`: 1 new file

## Verification
- Fresh DB: UNIQUE constraint present, schema v3
- v2→v3 migration: deduplicates rows, adds constraint
- Duplicate INSERT: raises IntegrityError
- Existing tests: all pass (updated test_idempotent for v3)
