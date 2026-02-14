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
- [🚧 v6.0 Codegen Service](milestones/v6.0-ROADMAP.md) (Phases 17-19) — in progress

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

### 🚧 v6.0 Codegen Service (In Progress)

**Milestone Goal:** LLM-powered plain-language explanation of validated formulas, Python code generation via SymPy, and AST-based Rust code generation — completing the pipeline from math to production code.

#### Phase 17: Codegen Research & Design

**Goal**: Investigate SymPy codegen API, Rust AST generation approaches, LLM explanation prompt design, and define service architecture
**Depends on**: v5.0 Validator complete
**Research**: Likely (AST-based Rust codegen, SymPy code generation, LLM prompt engineering for mathematical explanations)
**Research topics**: SymPy codegen module (pycode, ccode, rust-like output), Rust syn/quote crates for AST manipulation, LLM prompt design for LaTeX→plain-language explanation, N8N W5.3 analysis (what failed with regex approach)

Plans:
- [x] 17-01: Codegen Service Design + LLM Client Refactoring — completed 2026-02-14

#### Phase 18: Codegen Implementation

**Goal**: Implement Codegen service with LLM explanation, Python/SymPy codegen, and Rust AST codegen modules
**Depends on**: Phase 17
**Research**: Unlikely (established service patterns from v2-v5)
**Plans**: TBD

Plans:
- [ ] 18-01: TBD

#### Phase 19: Codegen Testing

**Goal**: Complete test suite for Codegen service (unit + integration + E2E with real LLM and CAS)
**Depends on**: Phase 18
**Research**: Unlikely (established test patterns)
**Plans**: TBD

Plans:
- [ ] 19-01: TBD

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
| 18. Codegen Implementation | v6.0 | 0/? | Not started | - |
| 19. Codegen Testing | v6.0 | 0/? | Not started | - |
