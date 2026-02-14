# Phase 16 Context: Validator Service Testing

## Scope

Complete test suite for the Validator Service (v5.0) — unit, integration, and E2E tests.

## What to Test

### Validator Service (3 modules, 480 LOC)

1. **consensus.py** (92 LOC) — Pure logic, no I/O
   - `ConsensusOutcome` enum: VALID, INVALID, PARTIAL, UNPARSEABLE
   - `ConsensusResult` dataclass: outcome, detail, engine_count, agree_count
   - `apply_consensus()` — decision matrix for 2-engine results

2. **cas_client.py** (108 LOC) — HTTP client (stdlib urllib)
   - `EngineResult` / `CASResponse` dataclasses
   - `CASClient.validate()` — POST /validate to CAS service
   - `CASClient.health()` — GET /health
   - Error handling: CASServiceError for HTTP/URL errors

3. **main.py** (295 LOC) — ValidatorHandler + helper functions
   - `handle_process()` — POST /process endpoint (batch validation)
   - `_query_formulas()` — DB query with paper_id/formula_id/force filters
   - `_store_validations()` — Write per-engine results to validations table
   - `_update_formula_stage()` — Stage transition (extracted → validated)
   - `_mark_formula_failed()` — Error handling (stage → failed)

## Test Strategy

### Unit Tests (mock all I/O)
- Consensus logic: all 9 combinations from decision matrix
- CASClient: mock urllib for validate/health/errors
- Query/store helpers: mock DB calls

### Integration Tests (real SQLite, mock HTTP)
- `_query_formulas()` with real DB, various filters
- `_store_validations()` — verify INSERT/DELETE idempotency
- `_update_formula_stage()` — stage transitions
- Full `/process` endpoint via HTTP (mock CAS, real DB)

### E2E Tests (real CAS at :8769)
- CAS service health check
- Real formula validation with SymPy + Maxima
- Full flow: insert formula → POST /process → verify DB results

## Existing Patterns (from v1.0-v4.0)

- conftest.py fixtures: `memory_db`, `tmp_db_path`, `initialized_db`, `sample_formula_data`
- Unit tests: class-based grouping (TestXxx), mock external calls
- Integration tests: real SQLite, test HTTP server on random port
- E2E tests: skip if service unavailable, `pytestmark = pytest.mark.e2e`

## Environment Notes

- CAS service: http://localhost:8769 (SymPy 1.14.0 + Maxima 5.45.1)
- MATLAB engine: temporaneamente non disponibile (licenza scaduta, ritornerà presto)
- E2E tests: CAS service attivo, test con dati reali
- 296 test esistenti devono continuare a passare (zero regressions)
