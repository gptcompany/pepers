# Phase 05 Context: Discovery Research & Design

## Phase Goal

Design the Discovery service — first microservice in the pipeline. Fetches papers from arXiv by configurable queries, enriches with Semantic Scholar metadata, optionally enriches with CrossRef (when journal DOI available). Stores results in SQLite via shared lib.

## Key Decisions

### Dependencies
- **`arxiv` pip package** (v2.4.0) for arXiv API access — handles rate limiting (3s), pagination, retries. Brings feedparser + requests as transitive deps.
- **`requests`** for Semantic Scholar and CrossRef APIs — already a dependency via arxiv package, ergonomic, well-tested.
- No need for `semanticscholar` or `habanero` libraries — simple REST JSON APIs, raw requests is sufficient.

### Service Design
- **Generic service**: accepts search queries as input via `/process` endpoint, not hardcoded keywords.
- **Input**: `{"query": "abs:\"Kelly criterion\" AND cat:q-fin.*", "max_results": 50}`
- **Output**: `{"papers_found": N, "papers_enriched": N, "errors": [...]}`
- **Port**: 8770 (as per ARCHITECTURE.md)
- **Config**: `RP_DISCOVERY_PORT`, `RP_DB_PATH`, `RP_DISCOVERY_MAX_RESULTS` (default 50)

### API Integration
- **arXiv**: `arxiv` package with `arxiv.Client(delay_seconds=3.0, num_retries=3)`
- **Semantic Scholar**: `requests.get(f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{arxiv_id}", params={"fields": "..."})`
  - Fields: citationCount, referenceCount, influentialCitationCount, s2FieldsOfStudy, tldr, openAccessPdf, venue, publicationVenue, externalIds
  - Rate: conservative 1 req/s (shared 1000 pool)
- **CrossRef**: only when arXiv paper has journal DOI
  - `requests.get(f"https://api.crossref.org/works/{doi}", headers={"User-Agent": "ResearchPipeline/1.0 (mailto:...)"})`
  - Store full response as `crossref_data` JSON blob
  - Rate: polite pool, 10 req/s single DOI

### Data Flow
```
POST /process {"query": "...", "max_results": 50}
    → arXiv search → list of papers
    → For each paper:
        → INSERT into papers table [stage=discovered]
        → Semantic Scholar lookup by ARXIV:{id}
            → UPDATE paper with S2 enrichment
        → If paper.doi exists (journal DOI):
            → CrossRef lookup by DOI
            → UPDATE paper.crossref_data
    → Return summary
```

### Error Handling
- arXiv: retry on 503 (exponential backoff via arxiv package)
- S2: retry on 429 (check Retry-After header), skip paper on persistent failure
- CrossRef: retry on 429, skip enrichment on failure (non-critical)
- All: 30s timeout per request
- Per-paper errors don't block pipeline — log and continue

### Rate Limiting
- arXiv: handled by arxiv package (3s delay)
- S2: `time.sleep(1.0)` between requests (conservative)
- CrossRef: `time.sleep(0.1)` between DOI lookups (polite pool allows 10/s)

### Deduplication
- Papers deduplicated by `arxiv_id` (UNIQUE constraint in DB)
- On duplicate: UPDATE existing record with latest metadata (not skip)

## Constraints
- Must use shared lib (BaseService, BaseHandler, @route, transaction, Paper model)
- Must follow patterns from v1.0 (JSON logging, SIGTERM, /health, /status, /process)
- SQLite via shared/db.py (not direct sqlite3)
- Config via shared/config.py (RP_ env vars)

## Testing Strategy (Phase 7)
- Unit tests: mock arXiv/S2/CrossRef responses with `unittest.mock.patch`
- Integration tests: real SQLite, mock HTTP APIs
- E2E tests: real API calls (arXiv, S2, CrossRef) — requires network, mark as @pytest.mark.e2e

## Open Questions
- None — all decisions made.

---
*Created: 2026-02-12*
