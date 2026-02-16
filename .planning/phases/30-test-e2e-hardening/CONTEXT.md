# Phase 30 Context: Test E2E Hardening

## Goal

Regression tests covering all fixes from Phase 28-29, ensuring stage transitions, batch overflow handling, and formula filtering are verified with real data flows.

## What Changed (Phase 28-29)

### Phase 28: Stage Transitions + Batch Overflow
1. **Validator** (`services/validator/main.py`): now UPDATEs `papers.stage` → "validated" after processing
2. **Codegen** (`services/codegen/main.py`): now UPDATEs `papers.stage` → "codegen" after processing
3. **Orchestrator** (`services/orchestrator/pipeline.py`): batch iteration loop — keeps calling validator/codegen until `formulas_processed == 0` (max 100 iterations, safety cap)
4. **LLM** (`shared/llm.py`): `max_tokens` 500 → 4096 for OpenRouter/Ollama

### Phase 29: LaTeX Filtering + Cleanup
1. **Extractor** (`services/extractor/latex.py`): `is_nontrivial()` heuristic rejects single Greek letters, pure subscripts, trivial fragments; `MIN_FORMULA_LENGTH` 3→10
2. **Codegen** (`services/codegen/generators.py`): `clean_latex()` strips 9 categories of unsupported macros before `parse_latex()`

## Regression Test Targets

### Integration Tests (DB-backed, mocked external services)

1. **Full stage progression**: paper goes discovered → analyzed → extracted → validated → codegen
   - Seed DB with paper at "extracted" stage + formulas
   - Call validator service → verify paper.stage = "validated"
   - Call codegen service → verify paper.stage = "codegen"

2. **Batch overflow**: >50 formulas processed across multiple iterations
   - Seed 75+ formulas in "extracted" stage
   - Mock validator to process 50 per call
   - Verify orchestrator loops until all processed
   - Verify merged batch results (sums, iterations count)

3. **Paper stage guard**: failed/rejected papers skipped by orchestrator
   - Seed paper with stage="rejected"
   - Verify `_resolve_stages` returns empty list

### Unit Tests (already covered in Phase 28-29, verify no regression)

4. **Formula filter**: `is_nontrivial()` rejects fragments, accepts real formulas
   - Already 14 tests in test_extractor.py

5. **LaTeX cleanup**: `clean_latex()` strips macros correctly
   - Already 20 tests in test_codegen.py

### E2E Tests (real services where available)

6. **End-to-end pipeline flow**: Single paper through full pipeline
   - Real DB, real extractor, mocked LLM/CAS
   - Verify every stage transition in sequence

## Existing Test Infrastructure

- **582 non-e2e + 43 e2e = 625 tests** (all passing)
- **Fixtures**: `memory_db()`, `discovered_paper_db()`, `analyzed_paper_db()`, `extracted_formula_db()`, `validated_formula_db()`
- **Pattern**: Thread-based services, random port allocation, `_get_free_port()`
- **DB**: SQLite in-memory or `tmp_path`

### Failure & Edge Case Tests (from confidence gate feedback)

7. **Batch partial failure**: Second batch iteration fails mid-way
   - Seed 75+ formulas, mock validator to succeed on first 50, fail on batch 2
   - Verify paper.stage stays at current level (not advanced)
   - Verify error list contains batch 2 errors

8. **Safety cap hit**: Batch loop reaches MAX_BATCH_ITERATIONS (100)
   - Mock service to always return `formulas_processed > 0` (infinite work)
   - Verify loop stops at 100 iterations
   - Verify graceful exit (no crash, results merged)

9. **Stage update atomicity**: Service processes but stage update fails
   - Verify that if processing succeeds but DB update fails, paper stays at previous stage
   - Verify formulas already processed are not lost (validations/generated_code rows exist)

10. **Filtered formulas don't cause infinite batch loops**
    - Seed formulas that `is_nontrivial()` would reject
    - Verify they're filtered at extraction, never reach validator/codegen batch queue
    - Verify batch loop terminates correctly with 0 remaining

## Decisions

- Focus on integration tests (DB-backed) over pure E2E (avoids external service deps)
- Test batch overflow with mocked service responses (deterministic)
- Test stage progression end-to-end with real DB + real services in-process
- Reuse existing fixtures, add new ones for multi-formula scenarios
- Include failure scenarios: partial batch failure, safety cap, atomicity
