# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v7.0 COMPLETE — all milestones shipped

## Current Position

Phase: 22 of 22 (Testing & Integration) — COMPLETE
Plan: 22-01 complete (1/1)
Status: ALL MILESTONES COMPLETE
Last activity: 2026-02-14 — v7.0 milestone complete

Progress: 7/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14
- v7.0 Orchestrator + Deploy: 3 phases, 850 LOC + 816 LOC tests — 2026-02-14

## Final Stats

- **Total tests**: 495 (461 non-e2e + 34 e2e), all passing
- **Total LOC**: ~7,500+ across 6 services + shared library + Docker
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose
- **Duration**: 5 days (2026-02-10 to 2026-02-14)

## Blockers/Concerns Carried Forward

- MATLAB license: temporarily unavailable (CAS service has SymPy + Maxima working)
- Gemini API: intermittent 503/429 errors (orchestrator retry handles: 3 retries, exponential backoff)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev
- Deploy Docker stack to Workstation (production run)

## Roadmap Evolution

- Milestone v7.0 created: Orchestrator + Deploy, 3 phases (Phase 20-22)
- Phase 20 complete: DESIGN.md with full architecture, Docker in-scope
- Phase 21 complete: Orchestrator (617 LOC) + Dockerfile + docker-compose.yml (223 LOC)
- Phase 22 complete: 63 new tests (43 unit + 15 integration + 5 e2e), 816 LOC tests
- Bug fix: DB stage → service name mapping in _resolve_stages()

## Session Continuity

Last session: 2026-02-14
Stopped at: ALL COMPLETE
Resume file: None
