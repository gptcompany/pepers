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
- 🚧 **v5.0 Validator Service** - Phases 14-16 (in progress)

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

### 🚧 v5.0 Validator Service (In Progress)

**Milestone Goal:** Multi-CAS formula validation with all-or-nothing consensus, including CAS microservice fix and detailed reporting

#### Phase 14: Research & Design

**Goal**: Investigate CAS microservice fix (SageMath engine failure), design validator service architecture, consensus logic, LaTeX simplification pipeline, validation report format
**Depends on**: Previous milestone complete
**Research**: Likely (CAS microservice debugging, external service integration at :8769)
**Research topics**: SageMath engine failure root cause in /media/sam/1TB/N8N_dev, SymPy API for formula parsing, LaTeX simplification approaches
**Plans**: TBD

Plans:
- [ ] 14-01: TBD (run /gsd:plan-phase 14 to break down)

#### Phase 15: Implementation

**Goal**: Fix CAS microservice SageMath engine, implement Validator service (simplification → multi-CAS dispatch → consensus → report → DB update)
**Depends on**: Phase 14
**Research**: Unlikely (implementing based on design)
**Plans**: TBD

Plans:
- [ ] 15-01: TBD

#### Phase 16: Testing

**Goal**: Unit tests (simplification, consensus logic), integration tests (CAS mock), E2E tests with real CAS engines
**Depends on**: Phase 15
**Research**: Unlikely (testing patterns established from v1.0-v4.0)
**Plans**: TBD

Plans:
- [ ] 16-01: TBD

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
| 14. Research & Design | v5.0 | 0/? | Not started | - |
| 15. Implementation | v5.0 | 0/? | Not started | - |
| 16. Testing | v5.0 | 0/? | Not started | - |
