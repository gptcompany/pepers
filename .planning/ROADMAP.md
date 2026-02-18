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
- [✅ v10.0 Production Hardening](milestones/v10.0-ROADMAP.md) (Phases 32-34) — SHIPPED 2026-02-17
- [✅ v11.0 CLI Providers + Batch Explain + API + Async](milestones/v11.0-ROADMAP.md) (Phases 35-37) — SHIPPED 2026-02-18

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

<details>
<summary>✅ v8.0 GitHub Discovery + Gemini Analysis (Phases 25-27) — SHIPPED 2026-02-15</summary>

- [x] **Phase 25: GitHub Discovery Research & Design** (1/1 plans) — completed 2026-02-15
- [x] **Phase 26: GitHub Discovery Implementation** (1/1 plans) — completed 2026-02-15
- [x] **Phase 27: GitHub Discovery Testing** (1/1 plans) — completed 2026-02-15

</details>

<details>
<summary>✅ v9.0 Pipeline Hardening — Post-E2E Fixes (Phases 28-30) — SHIPPED 2026-02-16</summary>

- [x] **Phase 28: Fix Stage Transitions + Batch Overflow** (1/1 plans) — completed 2026-02-16
- [x] **Phase 29: LaTeX Filtering + Cleanup** (1/1 plans) — completed 2026-02-16
- [x] **Phase 30: Test E2E Hardening** (1/1 plans) — completed 2026-02-16

</details>

### ✅ Phase 31: E2E Smoke Test CLI (Real Data)

**Goal**: Standalone smoke test CLI that runs the full 5-service pipeline on a real arXiv paper, verifies stage progression in DB, reports formula statistics
**Depends on**: v9.0 complete
**Plans**: 1/1 complete

Plans:
- [x] 31-01: Smoke test CLI + pytest wrapper (scripts/smoke_test.py 452 LOC, tests/e2e/test_smoke_real.py 90 LOC) — PASS on paper 2003.02743 (133 formulas, 107 codegen, 399 generated_code rows)

<details>
<summary>✅ v10.0 Production Hardening (Phases 32-34) — SHIPPED 2026-02-17</summary>

- [x] **Phase 32: Resilience — systemd Hardening** (2/2 plans) — completed 2026-02-17
- [x] **Phase 33: Reproducibility & Calibration** (1/1 plans) — completed 2026-02-17
- [x] **Phase 34: Orchestrator Smoke Test & Documentation** (1/1 plans) — completed 2026-02-17

</details>

### ✅ v11.0 CLI Providers + Batch Explain + API + Async (Phases 35-37) — SHIPPED 2026-02-18

- [x] **Phase 35: CLI Providers + Batch Explain** (1/1 plans) — completed 2026-02-18
- [x] **Phase 36: GET /generated-code + Async /run** (1/1 plans) — completed 2026-02-18
- [x] **Phase 37: E2E Testing + Documentation** (1/1 plans) — completed 2026-02-18

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
| 31. E2E Smoke Test CLI (Real Data) | post-v9.0 | 1/1 | Complete | 2026-02-16 |
| 32. Resilience — systemd Hardening | v10.0 | 2/2 | Complete | 2026-02-17 |
| 33. Reproducibility & Calibration | v10.0 | 1/1 | Complete | 2026-02-17 |
| 34. Orchestrator Smoke Test & Documentation | v10.0 | 1/1 | Complete | 2026-02-17 |
| 35. CLI Providers + Batch Explain | v11.0 | 1/1 | Complete | 2026-02-18 |
| 36. GET /generated-code + Async /run | v11.0 | 1/1 | Complete | 2026-02-18 |
| 37. E2E Testing + Documentation | v11.0 | 1/1 | Complete | 2026-02-18 |
