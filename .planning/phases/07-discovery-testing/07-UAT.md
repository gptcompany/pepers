---
status: complete
phase: 07-discovery-testing
source: 07-01-SUMMARY.md
started: 2026-02-12T20:35:00Z
updated: 2026-02-12T20:40:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Unit tests pass
expected: `pytest tests/unit/test_discovery.py -v` runs 44 tests, all green.
result: pass

### 2. Integration tests pass
expected: `pytest tests/integration/test_discovery_db.py -v` runs 15 tests, all green.
result: pass

### 3. E2E tests pass with real APIs
expected: `pytest tests/e2e/test_discovery_e2e.py -v -m e2e` runs 5 tests, all green (requires network).
result: pass

### 4. Full suite no regressions
expected: `pytest tests/ -m "not e2e"` runs 162 tests, all green (103 existing + 59 new non-E2E).
result: pass

### 5. Coverage target met
expected: `pytest --cov=services/discovery --cov-report=term-missing tests/ -m "not e2e"` shows >= 90% coverage for services/discovery/main.py.
result: pass

### 6. E2E tests skippable in default run
expected: `pytest tests/` without `-m e2e` excludes E2E tests (5 deselected).
result: issue
reported: "E2E tests run in default pytest invocation (167 passed, 0 deselected). Need explicit -m 'not e2e' to exclude them."
severity: minor

## Summary

total: 6
passed: 5
issues: 1
pending: 0
skipped: 0

## Issues for /gsd:plan-fix

- UAT-001: E2E tests not auto-skipped in default pytest run (minor) - Test 6
  root_cause: pytest markers are inclusive filters — `@pytest.mark.e2e` tags tests but doesn't skip them. Need `addopts = -m "not e2e"` in pyproject.toml or a `skipif` condition.
