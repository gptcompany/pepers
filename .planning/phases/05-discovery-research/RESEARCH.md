# Phase 05: Discovery Service — Research Findings

## API Summary

### arXiv API

| Aspect | Details |
|--------|---------|
| **Base URL** | `http://export.arxiv.org/api/query?` |
| **Auth** | None required |
| **Rate Limit** | 1 request every 3 seconds (mandatory) |
| **Response** | Atom 1.0 XML (parsed with feedparser) |
| **Max per call** | 2,000 results |
| **Max per query** | 30,000 results |
| **License** | Metadata: CC0, PDFs: copyright |

**Query syntax:**
- Field prefixes: `ti:`, `au:`, `abs:`, `cat:`, `all:`
- Boolean: `AND`, `OR`, `ANDNOT`
- Categories: `cat:q-fin.*` (all quantitative finance)
- Pagination: `start` + `max_results`
- Sort: `submittedDate`, `lastUpdatedDate`, `relevance`

**Key q-fin categories:**
- `q-fin.PM` — Portfolio Management (Kelly criterion, bet sizing)
- `q-fin.MF` — Mathematical Finance
- `q-fin.RM` — Risk Management
- `q-fin.ST` — Statistical Finance

**Python library:** `arxiv` v2.4.0 (Jan 2026) — handles rate limiting, pagination, retries automatically. Dependencies: feedparser + requests.

**Fields returned:** arxiv_id, title, summary (abstract), authors, published, updated, categories, primary_category, doi, journal_ref, pdf_url, comment.

### Semantic Scholar API

| Aspect | Details |
|--------|---------|
| **Base URL** | `https://api.semanticscholar.org/graph/v1/` |
| **Auth** | Optional (`x-api-key` header for higher limits) |
| **Rate Limit** | 1,000 req/s shared unauthenticated; higher with key |
| **Response** | JSON |
| **Batch** | POST `/paper/batch`, max 500 IDs per request |

**Paper lookup by arXiv ID:**
```
GET /paper/ARXIV:2107.05580?fields=title,citationCount,...
```

**Supported ID prefixes:** `ARXIV:`, `DOI:`, `CorpusId:`, `MAG:`, `ACL:`, `PMID:`, `URL:`

**Key fields (specify via `fields=`):**
- `title`, `abstract`, `year`, `venue`, `publicationDate`
- `citationCount`, `referenceCount`, `influentialCitationCount`
- `s2FieldsOfStudy` — `[{category, source}]`
- `tldr` — `{model, text}` AI-generated summary
- `openAccessPdf` — `{url, status}` (GOLD/GREEN/BRONZE)
- `publicationVenue` — `{id, name, type, issn}`
- `authors` — `[{authorId, name}]`
- `externalIds` — `{ArXiv, DOI, CorpusId, ...}`

**Python library:** `semanticscholar` v0.11.0 — typed responses, async support.

### CrossRef API

| Aspect | Details |
|--------|---------|
| **Base URL** | `https://api.crossref.org/` |
| **Auth** | None; `mailto` param for polite pool |
| **Rate Limit (polite)** | 10 req/s single DOI, 3 req/s search |
| **Rate Limit (public)** | 5 req/s single DOI, 1 req/s search |
| **Response** | JSON |
| **Corpus** | 165M+ records |

**CRITICAL:** arXiv-assigned DOIs (prefix `10.48550`) are registered with **DataCite**, NOT CrossRef. CrossRef only has journal/publisher DOIs.

**Enrichment strategy:**
1. Check arXiv metadata for journal DOI → if present, lookup in CrossRef
2. If no journal DOI → search CrossRef by title + first author
3. If no match → paper is preprint-only, skip CrossRef enrichment

**Key fields:** title, abstract (JATS XML, optional), author (with ORCID), container-title, publisher, license, funder, reference, is-referenced-by-count, subject, type.

**Python:** raw `requests` recommended (full control over rate limiting).

## Design Decisions Needed

### 1. Dependencies: pip packages vs stdlib

| Option | Pros | Cons |
|--------|------|------|
| `arxiv` + `requests` | Rate limiting, pagination, retries built-in | Extra deps, deviates from "no frameworks" constraint |
| `urllib.request` + `feedparser` | Minimal deps (feedparser for XML) | Manual rate limiting, pagination, retry logic |

**Recommendation:** Use `arxiv` package. It's a thin API wrapper (not a framework), and reimplementing its rate limiting + pagination + retry logic in stdlib would be YAGNI-violating busywork. feedparser is required either way for XML parsing.

### 2. Semantic Scholar: library vs raw requests

| Option | Pros | Cons |
|--------|------|------|
| `semanticscholar` lib | Typed responses, async | Extra dep |
| Raw `requests`/`urllib` | Full control, no dep | Manual field handling |

**Recommendation:** Raw `urllib.request` (stdlib). The S2 API is simple REST JSON — no XML parsing needed. Our Paper model already maps to S2 fields. A wrapper adds no value here.

### 3. CrossRef: library vs raw requests

**Recommendation:** Raw `urllib.request` (stdlib). Same rationale as S2 — simple JSON REST API. CrossRef enrichment is a secondary, optional step.

### 4. Rate Limiting Strategy

Three independent rate limiters needed:
- arXiv: 1 req/3s (strict, enforced by arXiv)
- Semantic Scholar: ~10 req/s conservative (1000 shared)
- CrossRef: ~3 req/s list, ~10 req/s single (polite pool)

Simple `time.sleep()` between requests is sufficient for daily batch of ~10-50 papers.

### 5. Error Handling & Retry

- arXiv: retry on HTTP 503 (overloaded), exponential backoff
- S2: retry on 429 (rate limited), check `Retry-After` header
- CrossRef: retry on 429, check `x-rate-limit-*` headers
- All: timeout of 30 seconds per request
- All: skip individual paper on persistent failure (don't block pipeline)

### 6. Enrichment Data Flow

```
arXiv search (by keywords + categories)
    → Parse: arxiv_id, title, abstract, authors, categories, doi, pdf_url, published_date
    → INSERT paper [stage=discovered]

For each paper:
    Semantic Scholar lookup (by ARXIV:{arxiv_id})
        → Enrich: semantic_scholar_id, citation_count, reference_count,
                  influential_citation_count, venue, fields_of_study, tldr, open_access
        → UPDATE paper

    CrossRef lookup (by journal DOI or title search)
        → Enrich: crossref_data (full JSON blob)
        → UPDATE paper

All enrichment is UPDATE, not INSERT — paper must exist from arXiv step.
```

## Sources

- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
- [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html)
- [arxiv.py on PyPI](https://pypi.org/project/arxiv/) (v2.4.0)
- [Semantic Scholar API Docs](https://api.semanticscholar.org/api-docs/)
- [Semantic Scholar Tutorial](https://www.semanticscholar.org/product/api/tutorial)
- [CrossRef REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [CrossRef Rate Limits Update (Nov 2025)](https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/)
- [arXiv DOI = DataCite, NOT CrossRef](https://info.arxiv.org/help/doi.html)
