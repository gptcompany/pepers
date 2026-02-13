# Phase 11 Context: Extractor Research & Design

## Phase Goal

Design the Extractor service that downloads PDFs from arXiv, sends them to RAGAnything for text extraction, parses LaTeX formulas from the resulting markdown, and stores formulas in the existing `formulas` table.

## Design Decisions

### 1. PDF Download Strategy

**Decision**: Direct HTTP download with `requests` + `urllib3.Retry`

**Rationale**:
- `Paper.pdf_url` is already populated by Discovery service — use it directly
- Fallback: construct URL from `arxiv_id` using `export.arxiv.org`
- No new dependency needed (`requests` already available)
- Conservative 3s delay between downloads (well within arXiv limits)
- Store PDFs in `data/pdfs/` relative to project root

**Rejected alternatives**:
- `arxiv` Python library `download_pdf()`: uses `arxiv.org` not `export.arxiv.org`, less control
- Don't download at all (RAGAnything needs local file path)

### 2. RAGAnything Integration

**Decision**: Synchronous polling with configurable timeout

**Rationale**:
- Submit PDF via POST `/process` → get `job_id`
- Poll `/jobs/{job_id}` every 10s until `completed` or `failed`
- Max timeout: 600s (10 min) per paper — matches RAGAnything default
- Circuit breaker check: query `/status` before submitting
- Read markdown from completed job's `output_dir`

**Rejected alternatives**:
- Webhook callback: adds complexity, our service would need to be a server AND client simultaneously during processing. Polling is simpler (KISS).
- Direct MinerU call: loses RAGAnything's knowledge graph, deduplication, and queue management

### 3. LaTeX Extraction Engine

**Decision**: Multi-pass regex with occupied-span tracking (stdlib `re` only)

**Rationale**:
- 5-pass extraction: environments → `\[...\]` → `$$...$$` → `\(...\)` → `$...$`
- Occupied-span set prevents overlapping matches
- Handles 95% of arXiv papers (which use standard LaTeX math delimiters)
- Zero additional dependencies — matches stdlib-first architecture
- Post-extraction filtering: dedup by hash, min complexity, skip trivial `$x$`

**Rejected alternatives**:
- `pylatexenc`: robust but ~10x slower, adds dependency. Save as potential future enhancement.
- `TexSoup`: tree navigation adds complexity we don't need
- Single-pass regex: misses overlapping patterns ($$...$$ vs $...$)

### 4. Formula Filtering

**Decision**: Three-tier filter
1. **Deduplication**: `latex_hash` (SHA-256) — already in Formula model
2. **Minimum complexity**: Must contain at least one LaTeX command (`\`) — filters currency `$500`
3. **Trivially short**: Skip formulas with `len(latex.strip()) < 3`

### 5. Context Extraction

**Decision**: 200-character window before and after each formula in the markdown text

**Rationale**:
- Downstream Validator needs context to understand what the formula represents
- N8N W3.2 used "2-3 sentences around formula" — 200 chars approximates this
- Stored in `Formula.context` field (already defined)

### 6. Service Architecture

**Decision**: Follow established service pattern (Analyzer/Discovery)

| Aspect | Value |
|--------|-------|
| Port | 8772 (per ARCHITECTURE.md) |
| Env prefix | `RP_EXTRACTOR_*` |
| Endpoints | `/health`, `/status`, `/process` |
| Module structure | `main.py` + `pdf.py` + `rag_client.py` + `latex.py` |
| Entry point | `python -m services.extractor.main` |

### 7. DB Schema

**Decision**: No schema changes needed

The existing `formulas` table (from v1.0) already has all required columns:
- `paper_id` (FK to papers)
- `latex` (raw LaTeX string)
- `latex_hash` (SHA-256, auto-computed by Pydantic validator)
- `description` (optional, for LLM-generated description later)
- `formula_type` ("inline" or "display")
- `context` (surrounding text)
- `stage` (default "extracted")
- `error` (for failed extractions)

Papers table update: stage `analyzed` → `extracted` after successful processing.

### 8. Error Handling

**Decision**: Per-paper error isolation

- If PDF download fails: set `paper.stage = 'failed'`, `paper.error = "pdf_download: {error}"`, continue to next paper
- If RAGAnything times out: set `paper.stage = 'failed'`, `paper.error = "raganything_timeout"`, continue
- If LaTeX extraction finds 0 formulas: set `paper.stage = 'extracted'` anyway (paper processed, just no formulas)
- If circuit breaker open: retry entire batch later (return 503 from /process)

## Constraints

- RAGAnything needs **local file path** — PDF must be downloaded to disk first
- RAGAnything max 2 concurrent jobs + 10 queue — process papers sequentially
- arXiv rate limit: 1 req/3s on export.arxiv.org
- ~10 papers/day batch — no parallelization needed (YAGNI)

## Integration Points

```
papers (stage='analyzed', score >= threshold)
  ↓ SELECT
Extractor (:8772)
  ├── pdf.py: Download PDF from export.arxiv.org → data/pdfs/
  ├── rag_client.py: POST /process to RAGAnything (:8767) → poll → get markdown
  ├── latex.py: Multi-pass regex → list[Formula]
  └── main.py: INSERT formulas, UPDATE papers.stage='extracted'
```
