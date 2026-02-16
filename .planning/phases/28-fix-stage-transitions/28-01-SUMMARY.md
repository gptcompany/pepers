# Summary 28-01: Fix Stage Transitions + Batch Overflow

## Result: COMPLETE

## Changes Made

### Bug 1: Validator papers.stage update (CRITICAL → FIXED)
- **File**: `services/validator/main.py` (+15 LOC)
- Added `_update_paper_stage()` function
- After formula processing loop, if any formula succeeded (processed > failed), updates `papers.stage` to `'validated'` for all papers in the batch
- Collects unique paper_ids from processed formulas

### Bug 2: Codegen papers.stage update (CRITICAL → FIXED)
- **File**: `services/codegen/main.py` (+16 LOC)
- Added `_update_paper_stage()` function (same pattern as validator)
- After formula processing loop, if any code was successfully generated (`sum(code_counts.values()) > 0`), updates `papers.stage` to `'codegen'`

### Bug 3: Orchestrator batch iteration loop (HIGH → FIXED)
- **File**: `services/orchestrator/pipeline.py` (+68 LOC)
- For `validator` and `codegen` stages, added a `while` loop that re-calls the service until `formulas_processed == 0`
- Safety cap: 100 iterations (100 × 50 = 5000 formulas max per paper)
- Added `_merge_batch_results()` static method to combine counters across iterations
- Logs each iteration count for observability

### Bug 4: OpenRouter/Ollama max_tokens truncation (MEDIUM → FIXED)
- **File**: `shared/llm.py` (+2 LOC, -2 LOC) — `max_tokens: 500 → 4096`, `num_predict: 500 → 4096`
- **File**: `services/codegen/explain.py` (+1 LOC, -1 LOC) — `num_predict: 500 → 4096` (hardcoded)
- Docstring updated to reflect new default

## Metrics

| Metric | Value |
|--------|-------|
| Files changed | 5 |
| LOC added | ~100 |
| LOC removed | ~5 |
| Tests passed | 543/543 |
| Type errors | 0 |
| Confidence gate (plan) | 95% AUTO_APPROVE |
| Confidence gate (impl) | 95% AUTO_APPROVE |

## Pipeline Flow After Fix

```
Paper: extracted → [validator processes formulas] → validated → [codegen generates code] → codegen
                    ↑ batch loop (50/iteration)      ↑ batch loop (50/iteration)
```

## Known Limitations

- If orchestrator is interrupted mid-batch, paper stage may already be advanced while some formulas remain unprocessed. A `force=true` re-run handles this.
- The `_update_paper_stage` function is duplicated in validator and codegen (6 LOC each). Acceptable per KISS — the function is trivially small.
