# Context: Phase 36 — GET /generated-code + Async POST /run

## Phase Goal

Add a dedicated GET endpoint for querying generated code (currently only accessible nested via /papers), and make POST /run asynchronous with polling support to prevent client timeouts on long pipeline runs.

## Scope Items

### 1. GET /generated-code

**File**: `services/orchestrator/main.py` (~40 LOC)

New `@route("GET", "/generated-code")`:
```
GET /generated-code?paper_id=29                     # All code for paper
GET /generated-code?paper_id=29&language=python      # Filter by language
GET /generated-code?paper_id=29&formula_id=551       # Specific formula
GET /generated-code?paper_id=29&limit=10&offset=0    # Pagination
```

Query: `SELECT g.*, f.latex, f.description FROM generated_code g JOIN formulas f ON f.id = g.formula_id WHERE f.paper_id = ?`

### 2. Async POST /run + GET /runs

**File**: `shared/db.py` — migration v4 (~15 LOC)
```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    params TEXT,
    results TEXT,
    errors TEXT,
    stages_completed INTEGER DEFAULT 0,
    stages_requested INTEGER DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
```

**File**: `services/orchestrator/pipeline.py` (~50 LOC)
- `_create_run_record()`, `_update_run_record()`, `get_run_status()`, `list_runs()`
- `run()` accepts optional `run_id`, persists to pipeline_runs

**File**: `services/orchestrator/main.py` (~40 LOC)
- `handle_run()`: generate run_id, INSERT, spawn `threading.Thread`, return HTTP 202
- `GET /runs`: list recent runs or single run by id

**File**: `scripts/smoke_test.py` (~30 LOC)
- Update orchestrator mode: POST /run → get run_id → poll GET /runs?id=xxx

### 3. Breaking Change

POST /run returns HTTP 202 `{"run_id": "...", "status": "running"}` instead of HTTP 200 with full results.

## Dependencies

- Phase 35 complete (CLI providers functional) ✅
- `shared/db.py` migration system (v3 exists) ✅
- `services/orchestrator/pipeline.py` PipelineRunner class ✅
