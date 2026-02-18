# Context: Phase 37 — E2E Testing + Documentation

## Phase Goal

Cross-feature E2E tests for v11.0, update ARCHITECTURE.md and RUNBOOK.md with CLI providers, batch explain, new endpoints, async /run, schema v4.

## Scope Items

### 1. E2E Tests

**File**: `tests/e2e/test_v11_e2e.py` (~120 LOC)
- Test async run: POST /run → poll GET /runs → verify completed
- Test GET /generated-code with seeded data
- Test batch explain with Ollama (skip if unavailable)

**File**: `tests/e2e/test_orchestrator_e2e.py` (~30 LOC modified)
- Update `test_run_returns_valid_structure` for async (HTTP 202, run_id, polling)
- Add test GET /generated-code

### 2. Documentation

**File**: `ARCHITECTURE.md`
- CLI providers section (claude_cli, codex_cli, data-driven config)
- `RP_LLM_FALLBACK_ORDER` env var
- Batch explain description
- New endpoints: GET /generated-code, GET /runs
- POST /run async breaking change
- pipeline_runs table (schema v4)
- Updated LOC and test counts

**File**: `docs/RUNBOOK.md`
- CLI providers configuration section
- `RP_LLM_FALLBACK_ORDER` documentation
- Async /run usage examples

## Dependencies

- Phase 36 complete (all new features functional)
