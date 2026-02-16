# Roadmap: Research Pipeline

## Overview

Replace the failed N8N W1-W5 research paper pipeline with standalone Python microservices. Starting with shared infrastructure (v1.0), then building each service incrementally: Discovery → Analyzer → Extractor → Validator → Codegen → Orchestrator. Extended with GitHub Discovery + Gemini analysis (v8.0).

## Domain Expertise

None

## Milestones

- [✅ v1.0 Foundation](milestones/v1.0-ROADMAP.md) (Phases 1-4) — SHIPPED 2026-02-10
- [✅ v2.0 Discovery Service](milestones/v2.0-ROADMAP.md) (Phases 5-7) — SHIPPED 2026-02-12
- [✅ v3.0 Analyzer Service](milestones/v3.0-ROADMAP.md) (Phases 8-10) — SHIPPED 2026-02-13
- [✅ v4.0 Extractor Service](milestones/v4.0-ROADMAP.md) (Phases 11-13) — SHIPPED 2026-02-13
- [✅ v5.0 Validator Service](milestones/v5.0-ROADMAP.md) (Phases 14-16) — SHIPPED 2026-02-14
- [✅ v6.0 Codegen Service](milestones/v6.0-ROADMAP.md) (Phases 17-19) — SHIPPED 2026-02-14
- [✅ v7.0 Orchestrator + Deploy](milestones/v7.0-ROADMAP.md) (Phases 20-22) — SHIPPED 2026-02-14
- [✅ v8.0 GitHub Discovery + Gemini Analysis](milestones/v8.0-ROADMAP.md) (Phases 25-27) — SHIPPED 2026-02-15
- [✅ v9.0 Pipeline Hardening — Post-E2E Fixes](milestones/v9.0-ROADMAP.md) (Phases 28-30) — SHIPPED 2026-02-16

## Phases

<details>
<summary>✅ v1.0 Foundation (Phases 1-4) — SHIPPED 2026-02-10</summary>

- [x] **Phase 1: Research & Design** (1/1 plans) — completed 2026-02-10
- [x] **Phase 2: Database & Models** (1/1 plans) — completed 2026-02-10
- [x] **Phase 3: HTTP Server & Config** (1/1 plans) — completed 2026-02-10
- [x] **Phase 4: Test Suite** (1/1 plans) — completed 2026-02-10

</details>

<details>
<summary>✅ v2.0 Discovery Service (Phases 5-7) — SHIPPED 2026-02-12</summary>

- [x] **Phase 5: Discovery Research & Design** (1/1 plans) — completed 2026-02-12
- [x] **Phase 6: Discovery Implementation** (1/1 plans) — completed 2026-02-12
- [x] **Phase 7: Discovery Testing** (1/1 plans) — completed 2026-02-12

</details>

<details>
<summary>✅ v3.0 Analyzer Service (Phases 8-10) — SHIPPED 2026-02-13</summary>

- [x] **Phase 8: Analyzer Research & Design** (1/1 plans) — completed 2026-02-13
- [x] **Phase 9: Analyzer Implementation** (1/1 plans) — completed 2026-02-13
- [x] **Phase 10: Analyzer Testing** (1/1 plans) — completed 2026-02-13

</details>

<details>
<summary>✅ v4.0 Extractor Service (Phases 11-13) — SHIPPED 2026-02-13</summary>

- [x] **Phase 11: Extractor Research & Design** (1/1 plans) — completed 2026-02-13
- [x] **Phase 12: Extractor Implementation** (1/1 plans) — completed 2026-02-13
- [x] **Phase 13: Extractor Testing** (1/1 plans) — completed 2026-02-13

</details>

<details>
<summary>✅ v5.0 Validator Service (Phases 14-16) — SHIPPED 2026-02-14</summary>

- [x] **Phase 14: Research & Design** (1/1 plans) — completed 2026-02-14
- [x] **Phase 15: Implementation** (2/2 plans) — completed 2026-02-14
- [x] **Phase 16: Testing** (1/1 plans) — completed 2026-02-14

</details>

<details>
<summary>✅ v6.0 Codegen Service (Phases 17-19) — SHIPPED 2026-02-14</summary>

- [x] **Phase 17: Codegen Research & Design** (1/1 plans) — completed 2026-02-14
- [x] **Phase 18: Codegen Implementation** (1/1 plans) — completed 2026-02-14
- [x] **Phase 19: Codegen Testing** (1/1 plans) — completed 2026-02-14

</details>

<details>
<summary>✅ v7.0 Orchestrator + Deploy (Phases 20-22) — SHIPPED 2026-02-14</summary>

#### Phase 20: Orchestrator Research & Design

**Goal**: Architecture design for orchestrator service — API contract, cron scheduling, stage coordination, error handling/retry, Docker compose layout
**Depends on**: v6.0 complete (all 5 services built)
**Research**: Likely (Docker compose orchestration patterns, cron integration, microservice coordination)
**Research topics**: Docker compose for multi-service Python apps, APScheduler vs cron for Python scheduling, retry/backoff patterns for HTTP microservice chains
**Plans**: 1/1 complete

Plans:
- [x] 20-01: Design orchestrator architecture + Docker deployment (DESIGN.md + PROJECT.md)

#### Phase 21: Orchestrator Implementation + Docker Deploy

**Goal**: Implement orchestrator service with /run endpoint + cron scheduler, Dockerfile and docker-compose.yml for all services
**Depends on**: Phase 20
**Research**: Unlikely (follows design from Phase 20)
**Plans**: 1/1 complete

Plans:
- [x] 21-01: Implement orchestrator service + Dockerfile + docker-compose.yml

#### Phase 22: Testing & Integration

**Goal**: Unit, integration, and E2E tests for orchestrator + full pipeline flow through all 5 services in Docker
**Depends on**: Phase 21
**Research**: Unlikely (established testing patterns from 6 milestones)
**Plans**: 1/1 complete

Plans:
- [x] 22-01: Unit, integration, and E2E tests for orchestrator (63 tests, 816 LOC)

</details>

### ✅ Phase 23: E2E Smoke Test (Real Papers)

**Goal**: Full pipeline smoke test with real arXiv papers — verify every service works end-to-end, honest assessment of bugs/performance/gaps
**Depends on**: v7.0 complete + all external services running
**Plans**: 1/1 complete

Plans:
- [x] 23-01: Full pipeline E2E smoke test with real papers — 6 bugs fixed, 5/6 services validated

### ✅ Phase 24: Skill Alignment + GET Endpoints (Retroactive)

**Goal**: Align /research and /research-papers skills to pipeline microservices, add GET /papers and GET /formulas query endpoints to orchestrator
**Depends on**: Phase 23
**Research**: Unlikely (internal patterns)
**Plans**: 1/1 complete

Plans:
- [x] 24-01: GET endpoints + skill alignment + E2E re-test (11 new integration tests, 0 bugs)

### ✅ v8.0 GitHub Discovery + Gemini Analysis (SHIPPED 2026-02-15)

**Milestone Goal:** Add GitHub repository search and deep analysis using Gemini CLI (1M context) with dynamic prompts generated from paper context (title, abstract, formulas). Enables the /research skill to find existing implementations of academic papers on GitHub.

#### Phase 25: GitHub Discovery Research & Design

**Goal**: Research Gemini CLI capabilities, GitHub REST API patterns, prompt engineering for code analysis → produce DESIGN.md
**Depends on**: Phase 24 (orchestrator GET endpoints available)
**Research**: Done (Gemini CLI verified, GitHub API verified, no existing OSS tool found)
**Plans**: 1/1 complete

Plans:
- [x] 25-01: Design GitHub Discovery architecture (DESIGN.md + CONTEXT.md + PROJECT.md)

#### Phase 26: GitHub Discovery Implementation

**Goal**: Implement github_search.py module (search, clone, analyze via Gemini CLI with SDK fallback), POST /search-github endpoint, update /research skill with dynamic prompt generation
**Depends on**: Phase 25
**Research**: Unlikely (follows design from Phase 25)
**Plans**: 1/1 complete

Plans:
- [x] 26-01: GitHub Discovery implementation (621 LOC github_search.py, schema v2, 4 models, 2 endpoints)

#### Phase 27: GitHub Discovery Testing

**Goal**: Unit tests for github_search module, integration tests for /search-github endpoint, E2E test with real GitHub repos and Gemini CLI analysis
**Depends on**: Phase 26
**Research**: Unlikely (established testing patterns)
**Plans**: 1/1 complete

Plans:
- [x] 27-01: GitHub Discovery tests (79 tests: 44 unit, 26 integration, 9 E2E with real APIs)

### ✅ v9.0 Pipeline Hardening — Post-E2E Fixes (SHIPPED 2026-02-16)

**Milestone Goal:** Fix 6 bugs found during E2E pipeline test on paper 15 (1806.05293, Kelly criterion stock markets). Stage transitions broken, batch overflow not handled, LaTeX fragments pass as formulas, codegen misinterprets LaTeX tags as variables.

#### Phase 28: Fix Stage Transitions + Batch Overflow

**Goal**: Fix paper stage not advancing after validator/codegen, add batch iteration loop in orchestrator, fix OpenRouter max_tokens truncation
**Depends on**: v8.0 complete
**Research**: Unlikely (bug fixes on existing internal patterns)
**Plans**: 1/1 complete

Bugs addressed:
- ✅ CRITICAL: validator/main.py does not UPDATE papers.stage after validation — FIXED
- ✅ CRITICAL: codegen/main.py does not UPDATE papers.stage after code generation — FIXED
- ✅ HIGH: orchestrator/pipeline.py calls validator/codegen once — FIXED (batch iteration loop)
- ✅ MEDIUM: shared/llm.py OpenRouter max_tokens=500 truncates responses — FIXED (→ 4096)

Plans:
- [x] 28-01: Fix stage transitions + batch overflow + max_tokens (5 files, ~100 LOC, 543 tests pass)

#### Phase 29: LaTeX Filtering + Cleanup

**Goal**: Add complexity filter to reject trivial LaTeX fragments, clean up LaTeX macros before parse_latex() to prevent codegen misinterpretation
**Depends on**: Phase 28
**Research**: Unlikely (regex + SymPy patterns already in codebase)
**Plans**: 1/1 complete

Bugs addressed:
- ✅ MEDIUM: extractor/latex.py MIN_FORMULA_LENGTH=3 allows fragments like ^{1}, \mu, \sigma — FIXED (is_nontrivial() heuristic)
- ✅ MEDIUM: codegen/generators.py does not strip \tag{N}, \label{}, \text{}, \pmb{}, \dots, \equiv — FIXED (clean_latex())
- ✅ MEDIUM: ~35% parse failure rate from unsupported LaTeX macros — MITIGATED (filter + cleanup)

Plans:
- [x] 29-01: LaTeX filtering + cleanup (4 files, 333 LOC, 582 tests pass, 34 new tests)

#### Phase 30: Test E2E Hardening

**Goal**: Regression tests covering stage transitions, batch overflow, and formula filtering — ensure all fixes from Phase 28-29 are verified with real data
**Depends on**: Phase 29
**Research**: Unlikely (established testing patterns from 8 milestones)
**Plans**: 1/1 complete

Plans:
- [x] 30-01: E2E Hardening tests (22 tests: 18 integration + 4 E2E, 932 LOC)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Research & Design | v1.0 | 1/1 | Complete | 2026-02-10 |
| 2. Database & Models | v1.0 | 1/1 | Complete | 2026-02-10 |
| 3. HTTP Server & Config | v1.0 | 1/1 | Complete | 2026-02-10 |
| 4. Test Suite | v1.0 | 1/1 | Complete | 2026-02-10 |
| 5. Discovery Research & Design | v2.0 | 1/1 | Complete | 2026-02-12 |
| 6. Discovery Implementation | v2.0 | 1/1 | Complete | 2026-02-12 |
| 7. Discovery Testing | v2.0 | 1/1 | Complete | 2026-02-12 |
| 8. Analyzer Research & Design | v3.0 | 1/1 | Complete | 2026-02-13 |
| 9. Analyzer Implementation | v3.0 | 1/1 | Complete | 2026-02-13 |
| 10. Analyzer Testing | v3.0 | 1/1 | Complete | 2026-02-13 |
| 11. Extractor Research & Design | v4.0 | 1/1 | Complete | 2026-02-13 |
| 12. Extractor Implementation | v4.0 | 1/1 | Complete | 2026-02-13 |
| 13. Extractor Testing | v4.0 | 1/1 | Complete | 2026-02-13 |
| 14. Research & Design | v5.0 | 1/1 | Complete | 2026-02-14 |
| 15. Implementation | v5.0 | 2/2 | Complete | 2026-02-14 |
| 16. Testing | v5.0 | 1/1 | Complete | 2026-02-14 |
| 17. Codegen Research & Design | v6.0 | 1/1 | Complete | 2026-02-14 |
| 18. Codegen Implementation | v6.0 | 1/1 | Complete | 2026-02-14 |
| 19. Codegen Testing | v6.0 | 1/1 | Complete | 2026-02-14 |
| 20. Orchestrator Research & Design | v7.0 | 1/1 | Complete | 2026-02-14 |
| 21. Orchestrator Implementation + Docker Deploy | v7.0 | 1/1 | Complete | 2026-02-14 |
| 22. Testing & Integration | v7.0 | 1/1 | Complete | 2026-02-14 |
| 23. E2E Smoke Test (Real Papers) | post-v7.0 | 1/1 | Complete | 2026-02-15 |
| 24. Skill Alignment + GET Endpoints | post-v7.0 | 1/1 | Complete | 2026-02-15 |
| 25. GitHub Discovery Research & Design | v8.0 | 1/1 | Complete | 2026-02-15 |
| 26. GitHub Discovery Implementation | v8.0 | 1/1 | Complete | 2026-02-15 |
| 27. GitHub Discovery Testing | v8.0 | 1/1 | Complete | 2026-02-15 |
| 28. Fix Stage Transitions + Batch Overflow | v9.0 | 1/1 | Complete | 2026-02-16 |
| 29. LaTeX Filtering + Cleanup | v9.0 | 1/1 | Complete | 2026-02-16 |
| 30. Test E2E Hardening | v9.0 | 1/1 | Complete | 2026-02-16 |
