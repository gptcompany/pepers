# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v7.0 Orchestrator + Deploy

## Current Position

Phase: 21 of 22 (Orchestrator Implementation + Docker Deploy) — COMPLETE
Plan: 21-01 complete (1/1)
Status: Ready for Phase 22
Last activity: 2026-02-14 — Phase 21 implementation complete

Progress: 6/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14

## Current Milestone

- v7.0 Orchestrator + Deploy (Phases 20-22)
  - Phase 20: Orchestrator Research & Design — COMPLETE (DESIGN.md + PROJECT.md updated)
  - Phase 21: Orchestrator Implementation + Docker Deploy — COMPLETE (840 LOC, 10/10 smoke tests)
  - Phase 22: Testing & Integration — Not started

## Blockers/Concerns Carried Forward

- MATLAB license: temporarily unavailable (CAS service has SymPy + Maxima working)
- Gemini API: intermittent 503/429 errors (orchestrator retry logic designed: 3 retries, exponential backoff)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev

## Roadmap Evolution

- Milestone v7.0 created: Orchestrator + Deploy, 3 phases (Phase 20-22)
- Phase 20 complete: DESIGN.md with full architecture, Docker in-scope
- Phase 21 complete: Orchestrator (617 LOC) + Dockerfile + docker-compose.yml (223 LOC)

## Session Continuity

Last session: 2026-02-14
Stopped at: Phase 21 complete, ready for Phase 22
Resume file: None
