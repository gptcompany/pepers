# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v5.0 Validator Service — Multi-CAS consensus validation

## Current Position

Phase: 14 of 16 (Research & Design)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-13 — Milestone v5.0 created

Progress: 4/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13

## Remaining Milestones

- v5.0 Validator (Multi-CAS consensus) ← IN PROGRESS
- v6.0 Codegen (Python/Rust generation)
- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Blockers/Concerns Carried Forward

- CAS microservice: only Maxima engine works (SageMath/MATLAB broken) — v5.0 will fix SageMath
- Gemini API: intermittent 503/429 errors (confidence gate rate-limited)

## Constraints (v5.0)

- CAS microservice lives in /media/sam/1TB/N8N_dev (separate repo)
- SymPy available as Python dependency
- CAS :8769 API uses `cas` parameter (maxima, sagemath, matlab)
- All-or-nothing consensus: any engine failure → formula invalid
- Must handle CAS engine timeouts gracefully

## Roadmap Evolution

- Milestone v5.0 created: Multi-CAS formula validation with consensus, 3 phases (Phase 14-16)

## Session Continuity

Last session: 2026-02-13
Stopped at: Milestone v5.0 initialization
Resume file: None
