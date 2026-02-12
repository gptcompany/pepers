# Phase 07 Context: Discovery Testing

## Phase Goal

Comprehensive test suite for the Discovery service (services/discovery/main.py, 448 LOC).
Three tiers: unit tests with mocked APIs, integration tests with real SQLite, E2E tests with real API calls.

## What Needs Testing

### Functions (7 standalone + 1 handler)
1. `extract_arxiv_id(result)` — Strip version suffix from arxiv.Result entry_id
2. `search_arxiv(query, max_results)` — arXiv client search, DataCite DOI filtering
3. `enrich_s2(arxiv_id)` — Semantic Scholar lookup with 429 retry
4. `enrich_crossref(doi)` — CrossRef lookup with 429 retry
5. `upsert_paper(db_path, paper)` — INSERT ON CONFLICT DO UPDATE with RETURNING
6. `update_paper_s2(db_path, paper_id, enrichment)` — S2 fields update
7. `update_paper_crossref(db_path, paper_id, crossref_data)` — CrossRef JSON blob
8. `DiscoveryHandler.handle_process(data)` — Full pipeline: validate → search → upsert → enrich

### Test Strategy
- **Unit tests** (`tests/unit/test_discovery.py`): Mock all external calls (arxiv, requests.get). Test each function in isolation.
- **Integration tests** (`tests/integration/test_discovery_db.py`): Real SQLite DB (tmp_path fixture), mock HTTP APIs. Test upsert/update and data flow.
- **E2E tests** (`tests/e2e/test_discovery_e2e.py`): Real API calls (arXiv, S2, CrossRef). Mark with `@pytest.mark.e2e`. Network required.

### Key Edge Cases
- `extract_arxiv_id`: versioned IDs (v1, v2), unversioned, URL variations
- `search_arxiv`: empty results, DataCite DOI filtering, missing fields
- `enrich_s2`: 200 success, 404 not found, 429 rate limit + retry, request exception
- `enrich_crossref`: 200 success, 404, 429 + retry, request exception
- `upsert_paper`: new insert, conflict update, missing fields, DB error
- `update_paper_s2`: with/without DOI field, DB error
- `update_paper_crossref`: valid JSON, DB error
- `handle_process`: missing query, invalid max_results, arXiv failure, partial enrichment errors

## Constraints
- Follow existing test patterns (see tests/unit/test_server.py, tests/conftest.py)
- Use existing fixtures: `initialized_db`, `sample_paper_row`, `clean_env`
- Add `e2e` marker to pyproject.toml
- No new dependencies (use unittest.mock, pytest fixtures)
- E2E tests must be skippable (network dependent)

## Open Questions
- None — strategy defined in 05-CONTEXT.md
