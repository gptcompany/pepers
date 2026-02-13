# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v4.0 Extractor Service — PDF processing + LaTeX formula extraction

## Current Position

Phase: 12 of 13 (Extractor Implementation)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-13 — Phase 11 completed (DESIGN.md produced)

Progress: 3/7 milestones shipped

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13

## Remaining Milestones

- v4.0 Extractor (RAGAnything + LaTeX regex) ← CURRENT (Phase 11 done, 12-13 remaining)
- v5.0 Validator (Multi-CAS consensus)
- v6.0 Codegen (Python/Rust generation)
- v7.0 Orchestrator + Deploy (systemd, monitoring)

## Blockers/Concerns Carried Forward

- CAS microservice: only Maxima engine works (SageMath/MATLAB broken)
- Gemini API: intermittent 503 errors
- ~~PDF sourcing strategy: needs research~~ → RESOLVED: export.arxiv.org with 3s rate limit

## Session Continuity

Last session: 2026-02-13
Stopped at: Phase 11 complete, Phase 12 ready
Next step: /pipeline:gsd 12
