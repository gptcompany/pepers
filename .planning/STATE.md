# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v5.0 Validator Service — Multi-CAS consensus validation

## Current Position

Phase: 15 of 16 (Implementation) — COMPLETE
Plan: 15-01 (CAS Microservice) + 15-02 (Validator Service) — both done
Status: Ready for Phase 16 (Testing)
Last activity: 2026-02-14 — Phase 15 implementation complete

Progress: 4/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13

## Remaining Milestones

- v5.0 Validator (Multi-CAS consensus) ← IN PROGRESS (Phase 15 done, Phase 16 next)
- v6.0 Codegen (Python/Rust generation)
- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Phase 15 Results

- CAS Microservice: 698 LOC, /media/sam/1TB/cas-service/ (standalone repo)
  - SymPy 1.14.0 + Maxima 5.45.1 engines
  - 4-phase LaTeX preprocessing pipeline
  - E2E verified: expressions + equations
- Validator Service: 480 LOC, services/validator/ (3 modules)
  - Consensus: VALID/INVALID/PARTIAL/UNPARSEABLE
  - CAS client: stdlib urllib.request (no new deps)
  - DB: validations table + formula stage transitions
- Total: 1178 LOC, all 296+ existing tests pass (zero regressions)

## Blockers/Concerns Carried Forward

- CAS microservice: NEW implementation replaces broken N8N_dev version
  - SymPy + Maxima work, SageMath/MATLAB dropped (SymPy is more reliable)
- Gemini API: intermittent 503/429 errors (confidence gate rate-limited)

## Constraints (v5.0)

- CAS microservice: NEW standalone repo at /media/sam/1TB/cas-service/
- SymPy + Maxima as CAS engines (replaced broken SageMath/MATLAB)
- Consensus: both engines must agree for VALID
- Engine timeouts handled (SymPy 5s, Maxima 10s)

## Future Tasks

- Isolate RAGAnything from N8N_dev into own repo
- Decommission old CAS service from N8N_dev

## Roadmap Evolution

- Milestone v5.0 created: Multi-CAS formula validation with consensus, 3 phases (Phase 14-16)
- Phase 14 (Research & Design): DESIGN.md complete
- Phase 15 (Implementation): CAS + Validator services complete

## Session Continuity

Last session: 2026-02-14
Stopped at: Phase 15 complete, ready for Phase 16 (Testing)
Resume file: None
