# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v8.0 GitHub Discovery + Gemini Analysis

## Current Position

Phase: 27 (GitHub Discovery Testing)
Plan: Not started
Status: **Ready to plan**
Last activity: 2026-02-15 — Phase 26 implementation completed

Progress: 7/7 milestones shipped + Phase 23-26 complete, v8.0 in progress

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
- Phase 25: GitHub Discovery Research & Design — DESIGN.md completed with full architecture, schema, API contracts, Gemini CLI integration — 2026-02-15
- Phase 26: GitHub Discovery Implementation — 621 LOC github_search.py (refactored from 297 LOC), schema v2 (github_repos + github_analyses), 4 Pydantic models, POST /search-github + GET /github-repos endpoints, 473 tests pass — 2026-02-15

## Final Stats

- **Total tests**: 473 (all passing)
- **Total LOC**: ~9,000+ across 6 services + shared library + Docker + GitHub Discovery
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose
- **Duration**: 6 days (2026-02-10 to 2026-02-15)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus

## v8.0 GitHub Discovery + Gemini Analysis

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 25. Research & Design | Gemini CLI, GitHub API, prompt engineering | Complete |
| 26. Implementation | github_search.py, POST /search-github, schema v2 | Complete |
| 27. Testing | Unit, integration, E2E with real repos | Not started |

### Phase 26 Deliverables

- `shared/db.py`: +38 LOC — github_repos + github_analyses tables, 4 indexes, schema v2
- `shared/models.py`: +69 LOC — GitHubRepo, GitHubAnalysis, SearchGitHubRequest, SearchGitHubResponse
- `services/orchestrator/github_search.py`: 621 LOC (refactored from 297 LOC head-start)
  - Multi-language search (Python, Rust, C++) with GitHub PAT auth
  - Rate limiting (GitHub API + Gemini RPM)
  - Gemini CLI with positional prompt + SDK fallback
  - Multi-language file reading (py, rs, cpp, hpp, c, h)
  - DB storage + paper context loading
  - Query generation from paper title keywords
  - All config via RP_GITHUB_* env vars
- `services/orchestrator/main.py`: +121 LOC — POST /search-github, GET /github-repos

## Blockers/Concerns

- Gemini CLI bugs may require CLI version pinning or workarounds
- Free tier rate limits may be insufficient for large batches (>30 repos)
- Repo clone disk usage — shallow clone + cleanup mitigates

## Session Continuity

Last session: 2026-02-15
Stopped at: Phase 26 complete, ready to plan Phase 27
Resume file: .planning/phases/26-github-discovery-implementation/26-01-PLAN.md
