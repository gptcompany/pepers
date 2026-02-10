# State: Research Pipeline

## Current Position

Phase: 3 of 4 (HTTP Server & Config)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-10 - Phase 02 Database & Models completed

Progress: █████░░░░░ 50%

## Accumulated Context

### Key Decisions
- SQLite over PostgreSQL (YAGNI — ~10 papers/day batch, zero infra overhead)
- Full independence from N8N (no shared containers, tables, or references)
- http.server stdlib (match CAS microservice pattern, no frameworks)
- CAS microservice (:8769) as reference architecture
- Single venv for all services
- Incremental milestones (shared lib first, then one service per milestone)
- Route dispatch via @route decorator (Phase 01 design)
- Standard error format with codes for AI agent consumption (Phase 01 design)
- RP_ env var prefix for configuration (Phase 01 design)
- WAL mode SQLite for concurrent reads (Phase 01 design)
- Ports 8770-8775 assigned to services (Phase 01 design)
- Maximal schema: all Semantic Scholar/CrossRef enrichment fields (Phase 02)
- Formula dedup via latex_hash SHA-256, no M:N table (Phase 02)
- Language column for generated_code extensibility (Phase 02)
- schema_version table for manual migration tracking (Phase 02)
- JSON fields via Pydantic field_validator for SQLite TEXT round-trip (Phase 02)

### Blockers/Concerns Carried Forward
- Python 3.10.12 on system vs 3.11 in .python-version (compatible, not blocking)

### Roadmap Evolution
- Milestone v1.0 Foundation created: shared infrastructure library, 4 phases (Phase 1-4)
- Phase 01 completed: CAS analysis, shared lib skeleton, ARCHITECTURE.md
- Phase 02 completed: SQLite schema (5 tables, 6 indexes), Pydantic models (8 models), DB layer

## Session Continuity

Last session: 2026-02-10
Stopped at: Phase 02 complete, Phase 03 ready
Resume file: None
