---
phase: 02-database-models
plan: 01
status: complete
subsystem: shared-lib
requires: [01-01]
provides: [sqlite-schema, pydantic-models, db-layer]
affects: [03-http-server-config, 04-test-suite]
tags: [database, models, foundation]
key-decisions:
  - "Maximal schema: all Semantic Scholar/CrossRef enrichment fields"
  - "Formula dedup via latex_hash (SHA-256), no M:N table"
  - "Language column for generated_code extensibility"
  - "schema_version table for manual migration tracking"
  - "JSON fields via Pydantic field_validator (TEXT <-> list/dict)"
key-files:
  - shared/db.py
  - shared/models.py
tech-stack:
  added: []
  patterns: [wal-mode, pydantic-validators, context-manager-transactions]
patterns-established:
  - "SCHEMA constant with executescript for idempotent init"
  - "transaction() context manager for auto-commit/rollback"
  - "JSON field round-trip: str -> validator -> Python type -> json.dumps -> SQLite TEXT"
  - "model_validator for auto-computed fields (latex_hash)"
  - "ConfigDict(from_attributes=True) for sqlite3.Row -> Pydantic model"
---

# Phase 02-01 Summary: Database & Models

## Accomplishments

### SQLite Database Layer (shared/db.py)
Implemented 3 functions + schema definition:
- `get_connection()`: WAL mode, foreign keys ON, Row factory, auto-creates parent dirs
- `transaction()`: Context manager with auto-commit/rollback
- `init_db()`: Idempotent schema creation (5 tables, 6 indexes)
- `SCHEMA` constant: papers, formulas, validations, generated_code, schema_version
- `INDEXES` constant: 6 indexes for common query patterns

### Pydantic Models (shared/models.py)
Implemented 8 models + helpers:
- `Paper`: 23 fields including all enrichment data (Semantic Scholar, CrossRef, fields_of_study, tldr, influential_citations, open_access)
- `Formula`: 10 fields with auto-computed `latex_hash` via `@model_validator`
- `Validation`: 8 fields for CAS engine results
- `GeneratedCode`: 8 fields with language column for extensibility
- `ServiceStatus`, `ProcessRequest`, `ProcessResponse`, `ErrorResponse`: API contract models
- JSON field validators: transparent TEXT <-> list/dict conversion for SQLite round-trips
- `PipelineStage` enum: 7 stages (discovered → complete/failed)

### Schema Design
5 tables with full referential integrity:
- `papers` (22 columns) — UNIQUE on arxiv_id
- `formulas` (10 columns) — FK to papers, latex_hash for dedup
- `validations` (8 columns) — FK to formulas
- `generated_code` (8 columns) — FK to formulas, language column
- `schema_version` (2 columns) — version tracking

## Verification Results
- All 3 functions work: get_connection, transaction, init_db
- 5 tables + 6 indexes created correctly
- WAL mode enabled, foreign keys enforced
- Full round-trip: Paper model -> model_dump -> INSERT -> SELECT -> dict -> model_validate -> matching fields
- FK constraints enforced (bad paper_id → IntegrityError)
- JSON fields round-trip: str → list/dict → json.dumps → TEXT → str → list/dict
- Auto-computed latex_hash: SHA-256 of raw LaTeX
- Schema version = 1
- Idempotent init (re-init preserves existing data)

## Issues Encountered
- Confidence gate verifier hallucinated SQLAlchemy in codebase (does not exist) — proceeded correctly
- Pyright type warnings on validator helpers — fixed with `Any` type parameter

## Deviations from Plan
None. All 3 tasks completed as specified.

## Next Phase Readiness
Phase 03 (HTTP Server & Config) is ready:
- `shared/server.py` stub needs implementation (BaseService, BaseHandler, @route decorator)
- `shared/config.py` stub needs implementation (load_config from env vars)
- Database layer is fully available for server endpoints to use
- No blockers
