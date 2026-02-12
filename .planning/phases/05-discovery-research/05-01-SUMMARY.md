---
phase: 05-discovery-research
plan: 01
status: complete
subsystem: discovery-service
requires: [v1.0]
provides: [api-research, design-decisions, discovery-architecture]
affects: [06-discovery-implementation, 07-discovery-testing]
tags: [research, design, api]
key-decisions:
  - "arxiv pip package for arXiv API (rate limiting, pagination, retries built-in)"
  - "requests for S2/CrossRef (already transitive dep of arxiv)"
  - "Generic service: queries as input, not hardcoded keywords"
  - "CrossRef only when journal DOI available (arXiv DOIs are DataCite, not CrossRef)"
  - "Per-paper error isolation: failures don't block pipeline"
  - "Conservative rate limiting: 3s arXiv, 1s S2, 0.1s CrossRef"
  - "Dedup by arxiv_id UNIQUE constraint, UPDATE on conflict"
key-files:
  - .planning/phases/05-discovery-research/RESEARCH.md
  - .planning/phases/05-discovery-research/05-CONTEXT.md
tech-stack:
  added: [arxiv (pip), requests (transitive)]
  patterns: [rest-api-integration, rate-limiting, enrichment-pipeline]
patterns-established:
  - "arXiv API via arxiv.Client with 3s delay"
  - "Semantic Scholar by ARXIV:{id} prefix lookup"
  - "CrossRef only for journal DOIs (10.48550 = DataCite)"
  - "Generic /process endpoint with query parameter"
---

# Phase 05-01 Summary: Discovery Research & Design

## Accomplishments

### API Research
Researched 3 academic APIs with comprehensive documentation:
- **arXiv**: Atom XML, 1 req/3s, `arxiv` pip package v2.4.0 recommended
- **Semantic Scholar**: REST JSON, 1000 req/s shared pool, lookup by `ARXIV:{id}` prefix
- **CrossRef**: REST JSON, polite pool (10 req/s single), arXiv DOIs NOT in CrossRef (DataCite instead)

### Design Decisions
- Generic Discovery service (queries as input parameters)
- Dependencies: `arxiv` package + `requests` (transitive)
- Data flow: arXiv search → S2 enrichment → conditional CrossRef enrichment → DB
- Error isolation per paper (don't block pipeline)
- Conservative rate limiting (simple time.sleep)

### Architecture Alignment
- Service follows shared lib patterns: BaseService, BaseHandler, @route, Paper model
- Port 8770, RP_ env vars, JSON logging, SIGTERM handling
- SQLite via shared/db.py with transaction context manager

## Issues Encountered
- arXiv DOIs (prefix 10.48550) are DataCite, not CrossRef — important discovery for enrichment strategy

## Deviations from Plan
None. All 3 tasks completed.

## Next Phase Readiness
Phase 06 (Discovery Implementation) is ready:
- All API details documented
- Design decisions finalized
- Shared lib interfaces available from v1.0
- No blockers

---
*Completed: 2026-02-12*
