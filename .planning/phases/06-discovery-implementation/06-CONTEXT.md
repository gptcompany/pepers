# Phase 06 Context: Discovery Service Implementation

## Phase Goal

Implement the Discovery service — first microservice in the pipeline. Takes arXiv search queries, discovers papers, enriches with Semantic Scholar and CrossRef metadata, persists to SQLite.

## Input Documents

All design decisions were made in Phase 05:
- **Design decisions**: `../05-discovery-research/05-CONTEXT.md`
- **API research**: `../05-discovery-research/RESEARCH.md`

## Key Implementation Requirements

- **Port**: 8770 (from shared/config.py SERVICE_PORTS)
- **Endpoint**: `POST /process` with `{"query": "...", "max_results": 50}`
- **Dependencies**: `arxiv>=2.4.0`, `requests>=2.28`
- **Pattern**: BaseService + BaseHandler + @route (from shared/server.py)
- **DB**: upsert via `ON CONFLICT(arxiv_id) DO UPDATE` (not INSERT OR IGNORE)
- **Error handling**: per-paper isolation, failures don't block pipeline
- **Rate limiting**: 3s arXiv (package), 1s S2 (sleep), 0.1s CrossRef (sleep)

## Constraints

- Must use shared lib exclusively (no direct sqlite3, no custom server)
- Follow v1.0 patterns (JSON logging, SIGTERM, /health, /status)
- Config via RP_ env vars (load_config)

---
*Created: 2026-02-12*
