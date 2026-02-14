# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v6.0 Codegen Service — Testing (Phase 19)

## Current Position

Phase: 18 of 19 (Codegen Implementation) — COMPLETE
Plan: 18-01 executed (confidence: 98%)
Status: Implementation complete, ready for Phase 19 (Testing)
Last activity: 2026-02-14 — Phase 18 implementation complete

Progress: 5/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14

## Remaining Milestones

- v6.0 Codegen (Python/Rust generation) — Phase 18 done, Phase 19 pending
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

## Session Continuity

Last session: 2026-02-14
Stopped at: Phase 18 complete, ready for Phase 19
Resume file: session-1771077732260-8zsnvo
