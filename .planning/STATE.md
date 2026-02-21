# State: PePeRS

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v12.0 Distribution & Branding — COMPLETE

## Current Position

Phase: 42 of 42 (Multi-Source Discovery — OpenAlex)
Plan: 42-01 complete
Status: Complete
Last activity: 2026-02-20 — Phase 42 complete: OpenAlex API client, schema v5, cross-source dedup, 1301 LOC added, 790 tests passing

Progress: 12/12 milestones shipped (v1.0-v12.0)

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

- **Total tests**: 582 non-e2e + 43 e2e = 625 total (all passing)
- **Total LOC**: ~10,600+ across 6 services + shared library + Docker + GitHub Discovery
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
| 28. Fix Stage Transitions + Batch Overflow | Paper stage updates, batch iteration, OpenRouter max_tokens | Complete |
| 29. LaTeX Filtering + Cleanup | Complexity filter, macro cleanup before parse_latex | Complete |
| 30. Test E2E Hardening | Regression tests for all fixes | Not started |

### Origin

E2E pipeline test on paper 15 (1806.05293, Kelly criterion stock markets, 6 pages):
- 104 formulas extracted, many spurious fragments
- Paper stage stuck at "extracted" after codegen
- 54 formulas never processed (batch limit 50)
- Codegen treats \tag{13} as variable
- ~35% parse_latex failure rate on complex notations

## Phase 28 Deliverables

- Stage transitions: validator + codegen now UPDATE papers.stage
- Batch iteration: orchestrator loops until all formulas processed (safety cap 5000)
- max_tokens: 500 → 4096 for OpenRouter/Ollama
- 543 tests pass, 0 type errors, ~100 LOC added

## Phase 29 Deliverables

- `services/extractor/latex.py`: +79 LOC — `is_nontrivial()` complexity heuristic, MIN_FORMULA_LENGTH 3→10
- `services/codegen/generators.py`: +43 LOC — `clean_latex()` strips 9 categories of unsupported macros
- `tests/unit/test_extractor.py`: +14 tests (is_nontrivial + filter_formulas)
- `tests/unit/test_codegen.py`: +20 tests (clean_latex + parse_formula integration)
- 582 non-e2e tests pass, 0 type errors, 333 LOC added

## Phase 30 Deliverables

- `tests/integration/test_hardening.py`: 567 LOC — 18 integration tests
  - TestStageTransitions (5): validator→validated, codegen→codegen, all-fail-no-advance, full progression
  - TestBatchIteration (6): batch processing 75 formulas, merge counters, safety cap at 100, partial failure, clean_latex
  - TestResolveStages (4): rejected/failed/codegen→empty, extracted→validator
  - TestFilteredFormulasNoInfiniteLoop (3): trivial filtered, nontrivial pass, zero-eligible terminates
- `tests/e2e/test_pipeline_e2e.py`: 362 LOC — 4 E2E tests
  - Full stage flow extracted→validated→codegen, multi-paper independence, all-fail negative path, batch overflow 60 formulas
- `tests/conftest.py`: +25 LOC — `multi_formula_db` fixture (75 formulas)
- 600 non-e2e + 47 e2e tests pass, 932 LOC added

## Phase 32 Deliverables

- `shared/db.py`: +45 LOC — MIGRATIONS dict, `_run_migrations()`, UNIQUE(paper_id, latex_hash) on formulas
- `shared/server.py`: +25 LOC — enhanced /health (DB check, schema_version, last_request_seconds_ago)
- `services/extractor/main.py`: +20 LOC — `_check_consistency()` startup check
- `services/validator/main.py`: +22 LOC — `_check_consistency()` startup check
- `services/codegen/main.py`: +20 LOC — `_check_consistency()` startup check
- `deploy/`: 7 new files — 6 systemd .service + 1 .target
- `tests/unit/test_db.py`: +80 LOC — 5 migration tests
- `tests/integration/test_resilience.py`: 190 LOC — 9 resilience tests

## Phase 33 Deliverables

- `shared/config.py`: +14 LOC — `_parse_float_env()`, `LLM_TEMPERATURE` (default 0.0)
- `shared/llm.py`: +31 LOC — temperature param on all providers, `seed=42`, `fallback_chain` threading
- `services/codegen/explain.py`: +2 LOC — use `LLM_TEMPERATURE` instead of hardcoded 0.2
- `ARCHITECTURE.md`: full rewrite — services, tests, schema v3, config, milestones v1.0-v10.0
- `tests/unit/test_llm.py`: 120 LOC — 9 temperature/seed unit tests
- `tests/e2e/test_determinism.py`: 70 LOC — 3x analyzer determinism calibration test
- `pyproject.toml`: +1 marker (`slow`)

## Phase 34 Deliverables

- `scripts/smoke_test.py`: +214 LOC — `--via-orchestrator` flag, `run_smoke_test_via_orchestrator()`, `--timeout` flag
- `tests/e2e/test_smoke_orchestrator.py`: 244 LOC — 11 test methods, 2 classes (Category A: 5 unit-style, Category B: 6 full E2E)
- `docs/RUNBOOK.md`: 452 LOC — 9-section operational runbook (services, startup, health, failures, recovery, config, performance, monitoring)

## Current Stats

- **Total tests**: 668 non-e2e + 60+ e2e = 728+ total (all passing, 0 regressions)
- **Total LOC**: ~13,000+ across 6 services + shared library + Docker + GitHub Discovery + deploy
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose + systemd units
- **Duration**: 9 days (2026-02-10 to 2026-02-18)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus
- **Schema version**: v4 (pipeline_runs table)
- **LLM determinism**: temperature=0, seed=42 on all configurable providers
- **LLM fallback order**: gemini_cli → codex_cli → claude_cli → openrouter → ollama

## v11.0 CLI Providers + Batch Explain + API + Async

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 35. CLI Providers + Batch Explain | Data-driven CLI registry, batch explain | Complete |
| 36. GET /generated-code + Async /run | New endpoints, async pipeline runs | Complete |
| 37. E2E Testing + Documentation | 12 E2E tests, ARCHITECTURE.md + RUNBOOK.md | Complete |

### Phase 35 Deliverables

- `shared/cli_providers.json`: 30 LOC — claude_cli, codex_cli, gemini_cli configs
- `shared/llm.py`: +130 LOC — `_load_cli_configs()`, `call_cli()`, `call_claude_cli()`, `call_codex_cli()`, refactored `call_gemini_cli()`, `RP_LLM_FALLBACK_ORDER` env var
- `services/codegen/explain.py`: +85 LOC — `explain_formulas_batch()`, `_parse_batch_response()`, `BATCH_EXPLANATION_SYSTEM_PROMPT`
- `services/codegen/main.py`: +5 LOC — batch-first in `handle_process()` loop
- `tests/unit/test_llm.py`: +14 new tests (180 LOC) — CLI registry, call_cli, fallback order
- `tests/unit/test_codegen.py`: +14 new tests (170 LOC) — batch parse, batch explain

### Phase 36 Deliverables

- `shared/db.py`: +15 LOC — migration v4 (pipeline_runs table + indexes)
- `services/orchestrator/pipeline.py`: +65 LOC — `_create_run_record()`, `_update_run_record()`, `get_run_status()`, `list_runs()`, run persistence in `run()`
- `services/orchestrator/main.py`: +75 LOC — `GET /generated-code`, `GET /runs`, async `POST /run` (HTTP 202 + thread), `_run_pipeline_async()`
- `scripts/smoke_test.py`: +20 LOC — async polling loop (POST /run → poll GET /runs)
- `tests/integration/test_orchestrator_db.py`: +150 LOC — 16 new tests (generated-code, runs, persistence)
- `tests/unit/test_db.py`: schema version 3→4 in assertions
- `services/codegen/explain.py`: `RP_CODEGEN_BATCH_SIZE` env var (default 50)

### Phase 37 Deliverables

- `tests/e2e/test_v11_e2e.py`: 244 LOC — 12 E2E tests
  - TestAsyncRun (5): HTTP 202, poll completion, invalid stages ×2, invalid paper_id
  - TestGetGeneratedCode (4): seeded data, language filter, missing paper_id, nonexistent
  - TestGetRuns (3): empty list, after async run, nonexistent id
- `tests/e2e/conftest.py`: 57 LOC — shared e2e_orchestrator fixture
- `tests/e2e/test_orchestrator_e2e.py`: refactored for async 202 + race-safe polling
- `ARCHITECTURE.md`: CLI providers, batch explain, schema v4, pipeline_runs, updated stats
- `docs/RUNBOOK.md`: CLI providers config, async /run examples, GET /generated-code
- `.env`: RP_LLM_FALLBACK_ORDER=gemini_cli,codex_cli,claude_cli,openrouter,ollama

## v12.0 Distribution & Branding

### Phases

| Phase | Goal | Status |
|-------|------|--------|
| 38. Branding & Naming | PePeRS naming, logo, professional README | Complete |
| 39. RAGAnything context_only | Chunk retrieval <2s for MCP | Complete |
| 40. MCP Server SSE | 8 tools via SSE on :8776 | Complete |
| 41. One-Click Install | Docker compose + uv tool install + pepers-mcp CLI | Complete |
| 42. Multi-Source Discovery (OpenAlex) | OpenAlex API, schema v5, cross-source dedup | Complete |

### Phase 42 Deliverables

- `services/discovery/openalex.py`: 269 LOC — OpenAlex API client (200M+ works, free, no API key)
- `services/discovery/main.py`: +112 LOC — adapter pattern multi-source, RP_DISCOVERY_SOURCES env var
- `shared/db.py`: +62 LOC — schema migration v5, source + openalex_id columns, arxiv_id nullable
- `shared/models.py`: +7 LOC — source/openalex_id fields in Pydantic models
- `tests/unit/test_openalex.py`: 436 LOC — unit tests
- `tests/integration/test_openalex_db.py`: 224 LOC — integration tests
- `tests/unit/test_db.py`: +189 LOC — migration v5 tests
- ARCHITECTURE.md, README.md, RUNBOOK.md updated

## Current Stats

- **Total tests**: 790 (all passing)
- **Total LOC**: ~14,300+ across 6 services + shared library + MCP server + Docker
- **Services**: 6 microservices (ports 8770-8775) + MCP server (8776) + Docker Compose + systemd units
- **Duration**: 11 days (2026-02-10 to 2026-02-21)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus
- **Schema version**: v5 (source + openalex_id columns)
- **LLM determinism**: temperature=0, seed=42 on all configurable providers
- **Discovery sources**: arXiv + OpenAlex (configurable via RP_DISCOVERY_SOURCES)

## Blockers/Concerns

None — v12.0 complete. All 42 phases shipped.

## Session Continuity

Last session: 2026-02-21
Stopped at: v12.0 milestone complete — all 42 phases done
Resume file: None
