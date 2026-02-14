# Roadmap: Research Pipeline

## Overview

Replace the failed N8N W1-W5 research paper pipeline with standalone Python microservices. Starting with shared infrastructure (v1.0), then building each service incrementally: Discovery → Analyzer → Extractor → Validator → Codegen → Orchestrator.

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

### ✅ v7.0 Orchestrator + Deploy — SHIPPED 2026-02-14

**Milestone Goal:** End-to-end pipeline orchestration with HTTP trigger + cron automation, deployed as Docker containers on Workstation.

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
