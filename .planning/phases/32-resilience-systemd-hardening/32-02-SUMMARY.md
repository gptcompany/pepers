# Summary: Plan 32-02 — Health + Consistency Checks + Resilience Tests

## Status: COMPLETE

## What was done

### Task 1: Enhanced /health with DB connectivity
- Added `last_request_time` class attribute to `BaseHandler`
- Request tracking: sets timestamp on every non-health request
- Enhanced `/health` response includes:
  - `db`: "ok" or "error: ..." (with connectivity check via SELECT 1)
  - `schema_version`: current migration version
  - `last_request_seconds_ago`: seconds since last non-health request
  - `status`: "degraded" if DB unreachable

### Task 2: Startup consistency checks
- **Extractor** (`_check_consistency`): detects papers at 'extracted' with 0 formulas
- **Validator** (`_check_consistency`): detects formulas with partial validations
- **Codegen** (`_check_consistency`): detects validated formulas with partial codegen
- All checks: read-only, wrapped in try/except, called at startup before service.run()

### Task 3: Integration tests
- `tests/unit/test_db.py`: +5 tests (TestSchemaMigration class)
  - fresh_db_has_unique_constraint, fresh_db_schema_version_3
  - migration_v2_to_v3, migration_deduplicates, duplicate_formula_rejected
- `tests/integration/test_resilience.py`: +9 tests
  - TestHealthEndpoint: db_status, degraded_on_bad_db, tracks_last_request
  - TestExtractorConsistency: detects_empty_extraction, no_warning_on_clean_db
  - TestValidatorConsistency: detects_partial_validations
  - TestCodegenConsistency: detects_partial_codegen
  - TestConsistencyGeneral: does_not_crash_on_empty_db
  - TestDuplicatePrevention: insert_or_ignore_for_idempotent_extraction

## Files modified
- `shared/server.py`: +25 LOC (health enhancement, request tracking)
- `services/extractor/main.py`: +20 LOC (_check_consistency)
- `services/validator/main.py`: +22 LOC (_check_consistency)
- `services/codegen/main.py`: +20 LOC (_check_consistency)
- `tests/unit/test_db.py`: +80 LOC (5 migration tests)
- `tests/integration/test_resilience.py`: 190 LOC new file (9 tests)

## Test results
- 614 non-E2E tests pass (was 600, +14 new)
- 0 regressions
