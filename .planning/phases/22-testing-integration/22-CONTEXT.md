# Context: Phase 22 — Testing & Integration

**Gathered:** 2026-02-14
**Source:** Test suite exploration + Phase 21 implementation

## Phase Goal

Unit, integration, and E2E tests for the orchestrator service (Phase 21).

## Test Pattern (from existing 6 milestones)

- **Unit tests**: `tests/unit/test_orchestrator.py` — pure logic, mocked HTTP/DB
- **Integration tests**: `tests/integration/test_orchestrator_db.py` — real SQLite, mocked services
- **E2E tests**: `tests/e2e/test_orchestrator_e2e.py` — real HTTP server, real DB

## Existing Stats

- 403 non-e2e + 29 e2e = 432 total tests
- Fixtures in tests/conftest.py (332 LOC)
- Markers: unit, integration, e2e

## What to Test

### Unit (mocked everything)
- `_resolve_stages()`: query mode, paper_id mode, batch mode, edge cases
- `_build_stage_params()`: parameter mapping for each service
- `_generate_run_id()`: format validation
- `_call_service_with_retry()`: success, 4xx no-retry, 5xx retry, timeout
- `create_scheduler()`: enabled/disabled, custom cron

### Integration (real DB, mocked HTTP)
- `get_pipeline_status()`: aggregate queries with real DB data
- `get_services_health()`: mocked /health responses
- `_get_paper_stage()`: real DB lookup
- `run()`: full pipeline with mocked service responses
- HTTP handler endpoints: /run, /status, /status/services

### E2E (real HTTP server)
- Orchestrator starts and responds on health
- POST /run with no services running → graceful error handling
- GET /status returns valid pipeline state
