# Summary: 17-01 Codegen Service Design + LLM Client Refactoring

## Result: Complete

**Date:** 2026-02-14

## What Was Done

- Researched SymPy codegen API (`codegen("C99")`, `codegen("Rust")`, `pycode()`)
- Researched ANTLR-based `parse_latex()` for LaTeX→SymPy conversion
- Analyzed N8N W5.3 Rust codegen failure (naive regex approach)
- Designed 3-module architecture: generators.py, explain.py, main.py
- Designed LLM client refactoring plan (shared/llm.py extraction from analyzer)
- Designed FormulaExplanation Pydantic model for structured LLM output
- Documented complete API contracts, DB operations, error handling matrix

## Deliverables

- DESIGN.md — Full service architecture (566 lines)
- RESEARCH.md — SymPy codegen + LLM prompt engineering research
- 17-CONTEXT.md — Phase context and decisions

## Key Decisions

- SymPy `codegen()` for C99/Rust (not manual string formatting)
- Ollama-first fallback order for codegen (local, free, faster)
- `parse_latex()` with ANTLR backend (more lenient than lark)
- Per-language error isolation (one failure doesn't block others)
- FormulaExplanation as validation-only model (stored as JSON in formulas.description)
