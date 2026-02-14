# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v6.0 Codegen Service — COMPLETE

## Current Position

Phase: 19 of 19 (Codegen Testing) — COMPLETE
Plan: 19-01 executed — 69 new tests, 86% coverage
Status: Milestone v6.0 complete
Last activity: 2026-02-14 — Phase 19 test suite complete

Progress: 6/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14

## Remaining Milestones

- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Phase 18 Summary

- shared/llm.py: 239 LOC — LLM client extracted from analyzer + enhanced
- services/codegen/generators.py: 181 LOC — SymPy codegen (C99/Rust/Python)
- services/codegen/explain.py: 88 LOC — LLM explanation (Ollama-first)
- services/codegen/main.py: 298 LOC — CodegenHandler + DB ops
- FormulaExplanation model added to shared/models.py
- Analyzer LLM re-exports (backward compat) + test mock paths updated
- 344/344 tests pass, 0 regressions
- antlr4-python3-runtime==4.11.1 installed

## Blockers/Concerns Carried Forward

- MATLAB license: temporarily unavailable (CAS service has SymPy + Maxima working)
- Gemini API: intermittent 503/429 errors (confidence gate rate-limited)
- parse_latex brittle on non-standard LaTeX (documented, per-formula error isolation)
- Rust integer promotion #26967 (documented, known SymPy issue)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev

## Roadmap Evolution

- Milestone v5.0 created: Multi-CAS formula validation with consensus, 3 phases (Phase 14-16)
- Phase 14 (Research & Design): DESIGN.md complete
- Phase 15 (Implementation): CAS + Validator services complete
- Phase 16 (Testing): Full test suite complete
- Milestone v6.0 created: Codegen Service (LLM explanation + Python/Rust codegen), 3 phases (Phase 17-19)
- Phase 17 (Research & Design): DESIGN.md complete
- Phase 18 (Implementation): Codegen service complete (806 LOC)
- Phase 19 (Testing): Test suite complete (69 tests, 960 LOC, 86% coverage)

## Phase 19 Summary

- tests/unit/test_codegen.py: 330 LOC — 39 tests (generators + explain mocked)
- tests/integration/test_codegen_db.py: 367 LOC — 20 tests (DB ops + HTTP endpoint)
- tests/e2e/test_codegen_e2e.py: 263 LOC — 10 tests (real SymPy + real Ollama)
- Total: 403 tests pass, 0 regressions (was 344)
- Coverage: explain.py 100%, generators.py 88%, main.py 82%
- Confidence gate: Plan 95%, Implementation 92%

## Session Continuity

Last session: 2026-02-14
Stopped at: Phase 19 complete, v6.0 milestone shipped
Resume file: None
