# Summary 11-01: Extractor Service Design Specification

## Outcome

Phase 11 (Extractor Research & Design) completed. Produced comprehensive design specification for the Extractor service, ready for Phase 12 implementation.

## Deliverables

| File | Purpose |
|------|---------|
| `RESEARCH.md` | Synthesized findings from 4 parallel research agents |
| `CONTEXT.md` | 8 design decisions with rationale |
| `11-01-PLAN.md` | 6-task execution plan |
| `DESIGN.md` | Complete implementation specification |

## Research Conducted

4 parallel research agents investigated:

1. **RAGAnything API** — Full endpoint documentation (v3.3-smart, port 8767). Async job processing with circuit breaker, hash dedup, max 2 concurrent + 10 queue.

2. **N8N W3 Workflow** — W3.1 PDF Extractor + W3.2 Formula Parser data flow mapped. PostgreSQL schema analyzed. Formula ID hashing pattern documented.

3. **LaTeX Regex Patterns** — 14+ delimiter types catalogued. 5-pass extraction with occupied-span tracking designed. Edge cases (escaped `\$`, `$$` vs `$`, multi-line) addressed. Library comparison completed (stdlib `re` recommended as primary).

4. **arXiv PDF Download** — URL patterns documented (new-style + old-style). Rate limiting policy: `export.arxiv.org`, 1 req/3s, descriptive User-Agent required. Existing `pdf_url` in papers table confirmed.

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| PDF download | `requests` + `urllib3.Retry` | Already in deps, full retry control |
| RAGAnything integration | Sync polling (not webhook) | KISS, no concurrent state management |
| LaTeX extraction | Stdlib `re` multi-pass | Zero deps, handles 95% of papers |
| Formula filtering | Hash dedup + min length + `\` check | Removes false positives |
| Context window | 200 chars | Approximates N8N W3.2's "2-3 sentences" |
| Schema changes | None needed | v1.0 `formulas` table already complete |
| Error handling | Per-paper isolation | One failure doesn't block batch |
| Service architecture | Same pattern as Analyzer | Consistency, `@route` decorator |

## Confidence Gates

| Gate | Score | Status |
|------|-------|--------|
| Context (CONTEXT.md) | 95% | AUTO_APPROVE |
| Plan (11-01-PLAN.md) | 98% | AUTO_APPROVE |

## Architecture

```
services/extractor/
├── __init__.py
├── main.py          # ExtractorHandler (~200 LOC)
├── pdf.py           # arXiv PDF download (~80 LOC)
├── rag_client.py    # RAGAnything client (~120 LOC)
└── latex.py         # LaTeX regex engine (~150 LOC)
```

Estimated ~550 LOC (comparable to Analyzer's 600 LOC).

## Next Steps

Phase 12 (Extractor Implementation) can implement directly from DESIGN.md.
