# Plan 06-01 Summary: Discovery Service Implementation

**Status:** COMPLETE
**Date:** 2026-02-12

## What Was Built

`services/discovery/main.py` — 448 LOC, first microservice in the pipeline.

### Functions (7)
1. `extract_arxiv_id(result)` — strip version suffix from arxiv.Result
2. `search_arxiv(query, max_results)` — arxiv.Client with 3s rate limit, DataCite DOI filtering
3. `enrich_s2(arxiv_id)` — Semantic Scholar lookup, 429 retry with Retry-After
4. `enrich_crossref(doi)` — CrossRef lookup with polite pool User-Agent
5. `upsert_paper(db_path, paper)` — ON CONFLICT(arxiv_id) DO UPDATE with RETURNING id
6. `update_paper_s2(db_path, paper_id, enrichment)` — S2 fields update
7. `update_paper_crossref(db_path, paper_id, crossref_data)` — CrossRef JSON blob

### Handler
- `DiscoveryHandler(BaseHandler)` with `POST /process`
- Input validation: query (required), max_results (1-500)
- Per-paper error isolation
- Returns: papers_found, papers_new, papers_enriched_s2, papers_enriched_cr, errors, time_ms

### Files Modified
- `pyproject.toml` — added arxiv>=2.4.0, requests>=2.28; added services* to packages.find
- `services/__init__.py` — created (empty)
- `services/discovery/__init__.py` — created (empty)
- `services/discovery/main.py` — created (448 LOC)

## Verification

| Check | Result |
|-------|--------|
| Existing tests | 103/103 passed |
| Syntax | All files clean |
| Imports | All symbols importable |
| Health endpoint | `{"status": "ok", "service": "discovery"}` |
| E2E: arXiv query | 3 papers found (Kelly criterion, q-fin) |
| E2E: S2 enrichment | 2/3 papers enriched |
| E2E: CrossRef enrichment | 1/3 papers enriched (1 had journal DOI) |
| E2E: Upsert | Second run: papers_new=0, no duplicates |
| DB contents | 3 papers with citation data verified |

## Key Design Decision

Changed `INSERT OR IGNORE` (from original plan) to `INSERT ... ON CONFLICT(arxiv_id) DO UPDATE` to match 05-CONTEXT.md requirement: "On duplicate: UPDATE existing record with latest metadata (not skip)".
