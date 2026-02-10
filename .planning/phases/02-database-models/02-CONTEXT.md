# Phase 02 Context: Database & Models

## Goal

Implement the SQLite database layer and Pydantic models by completing the stubs created in Phase 01. This includes: full schema definition, connection management with WAL mode, all 8 Pydantic models with fields and validators, and schema versioning.

## Decisions Made

### Schema Granularity: Maximal
Papers table includes all enrichment fields from Semantic Scholar/CrossRef:
- Core: title, abstract, authors, categories, doi, arxiv_id, pdf_url
- Enrichment: semantic_scholar_id, citation_count, reference_count, venue
- Extended: fields_of_study, influential_citation_count, open_access, tldr
- Metadata: crossref_data JSON blob for raw CrossRef response

### Formula Duplicates: Allow + latex_hash
- 1:N relationship (paper_id FK → papers.id)
- `latex_hash` column (SHA-256 of raw LaTeX) for future dedup
- No M:N junction table, no LaTeX normalization
- Query for similar: `SELECT * FROM formulas WHERE latex_hash = ?`

### Generated Code: Language Column
- Separate rows per language (python, rust, future languages)
- Columns: formula_id FK, language, code, metadata JSON
- Extensible without schema changes

### Schema Versioning: Version Table
- `schema_version` table with version number and applied_at timestamp
- Current version: 1
- Future migrations check version before applying

### JSON Fields: Pydantic Validators
- Stored as TEXT in SQLite
- `field_validator` in Pydantic models for auto-parse JSON string <-> list/dict
- Clean serialization: model handles conversion transparently

## Scope

### In Scope
- `shared/db.py`: get_connection(), transaction(), init_db() — full implementations
- `shared/models.py`: All 8 models with complete fields, validators, serialization helpers
- SQLite schema: papers, formulas, validations, generated_code, schema_version tables
- JSON field serialization via Pydantic validators
- WAL mode, foreign keys, Row factory

### Out of Scope
- Migration framework (YAGNI — version table for manual tracking only)
- Connection pooling (single connection per request, ~10 papers/day)
- Index optimization (premature — profile first in later phases)
- Test suite (Phase 04)

## Technical Constraints
- Python 3.10.12 compat via `from __future__ import annotations`
- pydantic>=2.0 (already in pyproject.toml)
- sqlite3 stdlib (no external DB drivers)
- ISO 8601 strings for datetime in SQLite
- `RP_DB_PATH` env var for database location

## Dependencies
- Phase 01 outputs: shared/ stubs, ARCHITECTURE.md, config.py
- No external service dependencies (pure local implementation)

## Existing Interfaces to Implement
- `shared/db.py`: 3 functions (get_connection, transaction, init_db)
- `shared/models.py`: 8 models (Paper, Formula, Validation, GeneratedCode, ServiceStatus, ProcessRequest, ProcessResponse, ErrorResponse) + PipelineStage enum
