# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v6.0 Codegen Service — LLM explanation + Python/Rust code generation

## Current Position

Phase: 17 of 19 (Codegen Research & Design)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-14 — Milestone v6.0 created

Progress: 5/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14

## Remaining Milestones

- v6.0 Codegen (Python/Rust generation) — IN PROGRESS
- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Blockers/Concerns Carried Forward

- MATLAB license: temporarily unavailable (CAS service has SymPy + Maxima working)
- Gemini API: intermittent 503/429 errors (confidence gate rate-limited)

## Constraints (v6.0)

- Codegen service: LLM plain-language explanation + Python codegen (SymPy) + Rust codegen (AST-based)
- Original W5.3 Rust codegen was naive regex JS → needs proper AST approach
- Tech stack: Python stdlib http.server (same as v1-v5), SymPy for Python codegen
- LLM: Ollama qwen3:8b for explanations (local, free, already deployed)
- Port: 8775 (next available in 8770-8775 range)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev

## Roadmap Evolution

- Milestone v5.0 created: Multi-CAS formula validation with consensus, 3 phases (Phase 14-16)
- Phase 14 (Research & Design): DESIGN.md complete
- Phase 15 (Implementation): CAS + Validator services complete
- Phase 16 (Testing): Full test suite complete
- Milestone v6.0 created: Codegen Service (LLM explanation + Python/Rust codegen), 3 phases (Phase 17-19)

## Session Continuity

Last session: 2026-02-14
Stopped at: Milestone v6.0 initialization
Resume file: None
