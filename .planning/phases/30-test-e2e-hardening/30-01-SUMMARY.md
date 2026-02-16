# Summary 30-01: E2E Hardening Regression Tests

## Result: COMPLETE

## Changes Made

### New File: `tests/integration/test_hardening.py` (567 LOC, 18 tests)

**TestStageTransitions (5 tests):**
- Validator updates paper.stage to "validated" after processing extracted formulas
- Codegen updates paper.stage to "codegen" after generating code
- All-formulas-fail: paper.stage stays at "extracted" (validator) / "validated" (codegen)
- Full progression: paper goes extracted → validated → codegen with DB verification at each step

**TestBatchIteration (6 tests):**
- 75 formulas processed across 3 batch iterations (50 + 25 + 0)
- Batch merge sums counters correctly across iterations
- Loop exits when `formulas_processed == 0`
- Safety cap: loop stops at 100 iterations (MAX_BATCH_ITERATIONS)
- Partial failure: first batch OK, second fails → errors captured
- clean_latex strips `\tag{N}` before codegen → parse succeeds

**TestResolveStages (4 tests):**
- Rejected paper returns empty stage list
- Failed paper returns empty stage list
- Paper at "codegen" (final) returns empty
- Paper at "extracted" starts from validator

**TestFilteredFormulasNoInfiniteLoop (3 tests):**
- Trivial fragments (`\alpha`, `^{1}`, `\mu`) rejected by filter_formulas
- Nontrivial formulas pass through correctly
- Zero eligible formulas → batch exits after 1 call with 0 processed

### New File: `tests/e2e/test_pipeline_e2e.py` (362 LOC, 4 tests)

**TestPipelineStageProgression (4 E2E tests):**
- Full flow: real HTTP validator+codegen services, paper extracted→validated→codegen, 9 generated_code rows (3 formulas × 3 languages)
- Multi-paper independence: 2 papers at different stages, each advances correctly
- Negative path: all formulas fail CAS → paper.stage NOT advanced
- Batch overflow: 60 formulas processed via real validator service in 2 calls (50 + 10)

### Modified: `tests/conftest.py` (+25 LOC)

- `multi_formula_db` fixture: DB with 1 paper + 75 extracted formulas for batch testing

## Metrics

| Metric | Value |
|--------|-------|
| Files changed | 3 |
| LOC added | 932 |
| New integration tests | 18 |
| New E2E tests | 4 |
| Total tests (non-e2e) | 600/600 passing |
| Total tests (e2e) | 47/47 passing |
| Total tests | 647 |
| Ruff errors (new files) | 0 |
| Confidence gate (plan) | 93% |
| Confidence gate (impl) | 93% |

## Acceptance Criteria

- [x] All 600+ existing tests still pass
- [x] 18 new integration tests pass
- [x] 4 new E2E tests pass
- [x] Stage transition regression: validator→"validated", codegen→"codegen" verified
- [x] Batch overflow regression: >50 formulas processed in multiple iterations
- [x] Safety cap: batch loop stops at MAX_BATCH_ITERATIONS (100)
- [x] Formula filter: trivial fragments rejected, real formulas accepted
- [x] clean_latex: `\tag{N}` stripped before codegen, parse succeeds
- [x] Negative path: all formulas fail → paper.stage not advanced
