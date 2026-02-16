# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v9.0 Pipeline Hardening — Post-E2E Fixes

## Current Position

Phase: 28 of 30 (Fix Stage Transitions + Batch Overflow)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-16 — Milestone v9.0 created

Progress: 8/8 milestones shipped, v9.0 in progress (0/3 phases)

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14
- v7.0 Orchestrator + Deploy: 3 phases, 850 LOC + 816 LOC tests — 2026-02-14
- v8.0 GitHub Discovery + Gemini Analysis: 3 phases, 621 LOC + 1307 LOC tests — 2026-02-15

## Post-v7.0 Phases (Completed)

- Phase 23: E2E Smoke Test — 6 bugs fixed, 5/6 services validated, production_ready: true — 2026-02-15
- Phase 24: Skill Alignment + GET Endpoints — /research and /research-papers skills aligned to pipeline, GET /papers and GET /formulas endpoints added, 11 new integration tests — 2026-02-15
- Phase 25: GitHub Discovery Research & Design — DESIGN.md completed with full architecture, schema, API contracts, Gemini CLI integration — 2026-02-15
- Phase 26: GitHub Discovery Implementation — 621 LOC github_search.py (refactored from 297 LOC), schema v2 (github_repos + github_analyses), 4 Pydantic models, POST /search-github + GET /github-repos endpoints — 2026-02-15
- Phase 27: GitHub Discovery Testing — 79 new tests (44 unit, 26 integration, 9 E2E with real APIs), all 586 tests pass — 2026-02-15

## Final Stats

- **Total tests**: 586 (543 non-e2e + 43 e2e, all passing)
- **Total LOC**: ~10,300+ across 6 services + shared library + Docker + GitHub Discovery
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose
- **Duration**: 6 days (2026-02-10 to 2026-02-15)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus

## v8.0 GitHub Discovery + Gemini Analysis

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 25. Research & Design | Gemini CLI, GitHub API, prompt engineering | Complete |
| 26. Implementation | github_search.py, POST /search-github, schema v2 | Complete |
| 27. Testing | Unit, integration, E2E with real repos | Complete |

### Phase 27 Deliverables

- `tests/unit/test_github_search.py`: 435 LOC — 44 unit tests
  - _extract_keywords, _get_github_headers, _check_rate_limit, build_dynamic_prompt
  - _parse_json_response, _read_repo_files, _generate_queries, clone/cleanup
- `tests/integration/test_github_search_db.py`: 503 LOC — 26 integration tests
  - _store_repo, _store_analysis, _load_paper_context, search_and_analyze (mocked)
  - POST /search-github endpoint, GET /github-repos endpoint, Pydantic models
- `tests/e2e/test_github_search_e2e.py`: 369 LOC — 9 E2E tests with real APIs
  - Real GitHub API search, real git clone + file reading
  - Real Gemini CLI analysis, full search_and_analyze flow
  - Real HTTP endpoints POST /search-github + GET /github-repos
- `tests/conftest.py`: +69 LOC — 3 new fixtures

## v9.0 Pipeline Hardening — Post-E2E Fixes

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 28. Fix Stage Transitions + Batch Overflow | Paper stage updates, batch iteration, OpenRouter max_tokens | Not started |
| 29. LaTeX Filtering + Cleanup | Complexity filter, macro cleanup before parse_latex | Not started |
| 30. Test E2E Hardening | Regression tests for all fixes | Not started |

### Origin

E2E pipeline test on paper 15 (1806.05293, Kelly criterion stock markets, 6 pages):
- 104 formulas extracted, many spurious fragments
- Paper stage stuck at "extracted" after codegen
- 54 formulas never processed (batch limit 50)
- Codegen treats \tag{13} as variable
- ~35% parse_latex failure rate on complex notations

## Blockers/Concerns

None — planning phase.

### Roadmap Evolution

- Milestone v9.0 created: Pipeline hardening post-E2E, 3 phases (Phase 28-30)

## Session Continuity

Last session: 2026-02-16
Stopped at: Milestone v9.0 initialization
Resume file: None
