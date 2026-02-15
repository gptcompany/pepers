# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v8.0 GitHub Discovery + Gemini Analysis

## Current Position

Phase: 25 (GitHub Discovery Research & Design)
Plan: Not started
Status: **Ready to plan**
Last activity: 2026-02-15 — Milestone v8.0 created

Progress: 7/7 milestones shipped + Phase 23-24 complete, v8.0 in progress

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14
- v7.0 Orchestrator + Deploy: 3 phases, 850 LOC + 816 LOC tests — 2026-02-14

## Post-v7.0 Phases (Completed)

- Phase 23: E2E Smoke Test — 6 bugs fixed, 5/6 services validated, production_ready: true — 2026-02-15
- Phase 24: Skill Alignment + GET Endpoints — /research and /research-papers skills aligned to pipeline, GET /papers and GET /formulas endpoints added, 11 new integration tests — 2026-02-15

## Final Stats

- **Total tests**: 497+ (463 non-e2e + 34 e2e), all passing
- **Total LOC**: ~7,500+ across 6 services + shared library + Docker
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose
- **Duration**: 6 days (2026-02-10 to 2026-02-15)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus

## v8.0 GitHub Discovery + Gemini Analysis

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 25. Research & Design | Gemini CLI capabilities, GitHub API, prompt engineering | Not started |
| 26. Implementation | github_search.py, POST /search-github, skill update | Not started |
| 27. Testing | Unit, integration, E2E with real repos | Not started |

### Key Decisions

- **Gemini CLI direct** (not PAL MCP) for repo analysis — domain-specific prompts, zero middleware
- **`--include-directories`** flag for native filesystem access (1M context)
- **Dynamic prompt** generated from paper context (title, abstract, formulas)
- **SDK fallback** when CLI unavailable (Docker containers)
- **Head start**: `github_search.py` module already created (will be refined in Phase 26)

## Blockers/Concerns

- Gemini CLI on host only, not in Docker — SDK fallback needed
- GitHub API rate limits (60 req/h unauthenticated, 5000 with PAT)
- Gemini CLI output format parsing may need refinement

## Session Continuity

Last session: 2026-02-15
Stopped at: Milestone v8.0 created, ready to plan Phase 25
Resume file: .planning/ROADMAP.md
