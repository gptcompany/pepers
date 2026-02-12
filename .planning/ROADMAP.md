# Roadmap: Research Pipeline

## Overview

Replace the failed N8N W1-W5 research paper pipeline with standalone Python microservices. Starting with shared infrastructure (v1.0), then building each service incrementally: Discovery → Analyzer → Extractor → Validator → Codegen → Orchestrator.

## Domain Expertise

None

## Milestones

- [✅ v1.0 Foundation](milestones/v1.0-ROADMAP.md) (Phases 1-4) — SHIPPED 2026-02-10
- [✅ v2.0 Discovery Service] — Phases 5-7 — SHIPPED 2026-02-12

## Phases

<details>
<summary>✅ v1.0 Foundation (Phases 1-4) — SHIPPED 2026-02-10</summary>

- [x] **Phase 1: Research & Design** (1/1 plans) — completed 2026-02-10
- [x] **Phase 2: Database & Models** (1/1 plans) — completed 2026-02-10
- [x] **Phase 3: HTTP Server & Config** (1/1 plans) — completed 2026-02-10
- [x] **Phase 4: Test Suite** (1/1 plans) — completed 2026-02-10

</details>

### ✅ v2.0 Discovery Service (SHIPPED 2026-02-12)

**Milestone Goal:** First microservice in the pipeline — fetches arXiv papers by keywords, enriches with Semantic Scholar and CrossRef metadata, stores in SQLite DB.

#### Phase 5: Discovery Research & Design

**Goal**: Research arXiv, Semantic Scholar, and CrossRef APIs. Design Discovery service endpoints, data flow, error handling, and rate limiting strategy.
**Depends on**: v1.0 Foundation complete
**Research**: Likely (external API integration — arXiv, Semantic Scholar, CrossRef)
**Research topics**: arXiv API query syntax and rate limits, Semantic Scholar API v2 (paper search, batch details, fields), CrossRef REST API (DOI lookup, metadata enrichment), rate limiting strategies for academic APIs
**Plans**: 1 plan in 1 wave

Plans:
- [x] 05-01: API research + design decisions + architecture alignment

#### Phase 6: Discovery Implementation

**Goal**: Implement Discovery service — arXiv fetcher, Semantic Scholar enricher, CrossRef enricher, HTTP endpoints (/process, /health, /status), DB persistence via shared lib.
**Depends on**: Phase 5
**Research**: Unlikely (follows patterns established in v1.0 + Phase 5 research)
**Plans**: TBD

Plans:
- [x] 06-01: arXiv search + S2/CrossRef enrichment + HTTP handler + DB persistence

#### Phase 7: Discovery Testing

**Goal**: Comprehensive test suite — unit tests with mocked APIs, integration tests with real SQLite, E2E tests with real API calls (arXiv, Semantic Scholar, CrossRef).
**Depends on**: Phase 6
**Research**: Unlikely (standard pytest patterns from v1.0)
**Plans**: TBD

Plans:
- [x] 07-01: Discovery service test suite (unit + integration + E2E)

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
