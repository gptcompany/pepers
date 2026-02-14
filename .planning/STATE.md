# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v6.0 Codegen Service — Planning next milestone

## Current Position

Phase: 16 of 16 (Testing) — COMPLETE
Plan: 16-01 (Validator Test Suite) — done
Status: v5.0 Milestone COMPLETE, ready for v6.0
Last activity: 2026-02-14 — Phase 16 testing complete

Progress: 5/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14

## Remaining Milestones

- v6.0 Codegen (Python/Rust generation)
- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Phase 16 Results

- 56 new tests: 30 unit + 18 integration + 8 E2E
- 363 total tests (was 307), all passing
- Coverage: 87% on validator module (consensus.py 100%, cas_client.py 96%)
- E2E with real CAS: SymPy + Maxima on real formulas
- MATLAB engine: temporarily unavailable (license expired, will return)

## v5.0 Totals

- CAS Microservice: 698 LOC (standalone repo /media/sam/1TB/cas-service/)
- Validator Service: 480 LOC (services/validator/, 3 modules)
- Test Suite: 56 tests, 751 LOC, 87% coverage
- Total v5.0: 1178 impl LOC + 751 test LOC

## Blockers/Concerns Carried Forward

- MATLAB license: temporarily unavailable (CAS service has SymPy + Maxima working)
- Gemini API: intermittent 503/429 errors (confidence gate rate-limited)

## Constraints (v5.0)

- CAS microservice: standalone repo at /media/sam/1TB/cas-service/
- SymPy + Maxima + MATLAB as CAS engines (MATLAB license temp. unavailable)
- Consensus: both engines must agree for VALID
- Engine timeouts handled (SymPy 5s, Maxima 10s)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev

## Roadmap Evolution

- Milestone v5.0 created: Multi-CAS formula validation with consensus, 3 phases (Phase 14-16)
- Phase 14 (Research & Design): DESIGN.md complete
- Phase 15 (Implementation): CAS + Validator services complete
- Phase 16 (Testing): Full test suite complete

## Session Continuity

Last session: 2026-02-14
Stopped at: v5.0 complete, ready for v6.0
Resume file: None
