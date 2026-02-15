# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v8.0 GitHub Discovery + Gemini Analysis

## Current Position

Phase: 26 (GitHub Discovery Implementation)
Plan: Not started
Status: **Ready to plan**
Last activity: 2026-02-15 — Phase 25 DESIGN.md completed

Progress: 7/7 milestones shipped + Phase 23-25 complete, v8.0 in progress

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
| 25. Research & Design | Gemini CLI, GitHub API, prompt engineering | Complete |
| 26. Implementation | github_search.py refine, POST /search-github, schema extension | Not started |
| 27. Testing | Unit, integration, E2E with real repos | Not started |

### Key Decisions (from Phase 25 Research)

- **Gemini CLI on host**, SDK fallback in Docker — CLI has `--include-directories` for 1M context
- **GitHub PAT** from SSOT — 30 req/min search rate
- **New SQLite tables**: `github_repos` + `github_analyses` with FK to papers
- **Python + Rust + C++** language scope — aligned with codegen service
- **Gemini 2.5 Pro** for analysis (configurable via `RP_GITHUB_ANALYSIS_MODEL`)
- **Papers With Code shut down** July 2025 — no existing OSS alternative found
- **Head-start module** (297 LOC) validates architecture, gaps identified for Phase 26

### Research Findings

- Gemini CLI free tier: 5 RPM / 100 RPD (cut Dec 2025). Paid Tier 1: 150-300 RPM
- GitHub search: 30 req/min with PAT, max 1000 results, `in:readme` qualifier essential
- Known bugs: `--include-directories` (#13669), JSON output (#9009) — need testing
- Live test: "kelly criterion language:python stars:>5" → 11 results found

## Blockers/Concerns

- Gemini CLI bugs may require CLI version pinning or workarounds
- Free tier rate limits may be insufficient for large batches (>30 repos)
- Repo clone disk usage — shallow clone + cleanup mitigates

## Session Continuity

Last session: 2026-02-15
Stopped at: Phase 25 complete, ready to plan Phase 26
Resume file: .planning/phases/25-github-discovery-research-design/DESIGN.md
