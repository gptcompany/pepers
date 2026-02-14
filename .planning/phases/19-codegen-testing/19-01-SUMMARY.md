# Summary: 19-01 Codegen Service Test Suite

## Result: Complete

**Date:** 2026-02-14

## What Was Done

- Created tests/unit/test_codegen.py (330 LOC, 39 tests)
  - parse_formula: fraction, multi-var, env stripping, dollar signs, empty, trig, sqrt
  - generate_c99/rust/python: output structure, variables, naming
  - generate_all: valid/invalid LaTeX, error isolation, metadata
  - explain_formula: Ollama success, Gemini fallback, all-fail, schema passing
- Created tests/integration/test_codegen_db.py (367 LOC, 20 tests)
  - _query_formulas: by paper_id, formula_id, force, limit, JOIN paper_title
  - _store_generated_code: insert, overwrite, error, multi-language
  - _update_formula_description, _update_formula_stage, _mark_formula_failed
  - HTTP POST /process: empty, with/without explanation, specific paper
- Created tests/e2e/test_codegen_e2e.py (263 LOC, 10 tests)
  - Real SymPy codegen: Kelly, polynomial, fraction, trig, sqrt, exp, multi-var
  - Real Ollama LLM explanation (skip if unavailable)
  - Full HTTP flow: insert → POST /process → verify DB

## Metrics

| Metric | Value |
|--------|-------|
| New tests | 69 (39 unit + 20 integration + 10 e2e) |
| Test LOC | 960 |
| Coverage | 86% (explain 100%, generators 88%, main 82%) |
| Total tests | 403 (was 344) |
| Regressions | 0 |
| Lint | Clean (ruff) |
| Confidence gate | Plan 95%, Impl 92% |
