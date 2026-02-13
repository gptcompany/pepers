# Phase 11 Research: Extractor Service Design

## Research Topics

1. RAGAnything API (service at :8767)
2. N8N W3 Workflow Analysis (PDF extraction + formula parsing)
3. LaTeX Formula Regex Patterns
4. arXiv PDF Download Patterns

---

## 1. RAGAnything API

**Service**: RAGAnything v3.3-smart on port 8767 (systemd, already deployed)
**Storage**: `/media/sam/1TB/N8N_dev/rag_knowledge_base/`
**Output**: `/media/sam/1TB/N8N_dev/extracted/raganything/`

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Full status + config |
| `/status` | GET | Quick status (circuit breaker + jobs) |
| `/process` | POST | Submit PDF for async processing |
| `/jobs/{id}` | GET | Poll job status |
| `/jobs` | GET | List all jobs |
| `/query` | POST | Semantic search on knowledge graph |
| `/reset-circuit-breaker` | GET | Manual circuit breaker reset |

### POST /process — Key Contract

**Request:**
```json
{
  "pdf_path": "/media/sam/1TB/path/to/paper.pdf",
  "paper_id": "arxiv:2401.12345",
  "webhook_url": "http://localhost:8772/webhook",
  "force_parser": "mineru",
  "force_reprocess": false
}
```

**Responses:**
- `202 Accepted`: Job queued → poll `/jobs/{job_id}` for completion
- `200 OK`: Already processed (cached) → `output_dir` + `markdown_length` returned
- `400`: Missing pdf_path or paper_id
- `404`: PDF file not found
- `429`: Queue full (>12 jobs)
- `503`: Circuit breaker open

**Job Status Values:** `queued` → `processing` → `completed` | `failed`

**Completed Job Result:**
```json
{
  "success": true,
  "indexed": true,
  "output_dir": "/workspace/1TB/N8N_dev/extracted/raganything/arxiv_2401_12345",
  "markdown_length": 45678,
  "entities_extracted": true,
  "parser": "mineru",
  "pdf_hash": "a1b2c3d4e5f6"
}
```

### Configuration

| Setting | Value |
|---------|-------|
| MAX_CONCURRENT_JOBS | 2 |
| MAX_QUEUE_DEPTH | 10 |
| PROCESS_TIMEOUT | 14400s (4h) |
| Circuit Breaker | 3 failures → open, 300s recovery |
| Parser | MinerU primary, docling fallback |
| Embedding | BAAI/bge-large-en-v1.5 (1024-dim) |

### Path Mapping

Container paths are transparently mapped:
- `/workspace/1TB/...` ↔ `/media/sam/1TB/...`

---

## 2. N8N W3 Workflow Analysis

### Data Flow

```
W2.3 (Relevance Scorer, score >= 70)
  ↓
W3.1 (PDF Extractor, ID: 6dcjxKkywwpzrZOm)
  ├── POST /process to RAGAnything (:8767)
  ├── Receives markdown + extraction metadata
  └── Stores extracted text
       ↓
W3.2 (Formula Parser, ID: 3l2w45ZfCDw6Q06M)
  ├── Regex LaTeX detection ($...$, $$...$$, \[...\], \begin{equation})
  ├── Context extraction: 2-3 sentences around formula
  ├── Formula ID: hash(paper_id + section + latex_expression)
  └── INSERT INTO formulas table
       ↓
W4.1 (Multi-CAS Validator)
```

### Key Design Lessons from W3

1. **Async processing**: W3.1 submits to RAGAnything and polls for completion
2. **Formula deduplication**: Hash-based IDs prevent duplicate formulas
3. **Context is critical**: Surrounding text needed for downstream CAS validation
4. **PostgreSQL schema** (N8N): papers, formulas, validations, generated_code
   - Our SQLite schema already mirrors this structure

---

## 3. LaTeX Formula Regex Patterns

### Delimiters (14+ types, priority order)

| Priority | Delimiter | Type | Reliability |
|----------|-----------|------|-------------|
| 1 | `\begin{equation}...\end{equation}` | Display (numbered) | Highest |
| 1 | `\begin{align}...\end{align}` | Display (multi-line) | Highest |
| 1 | `\begin{gather}...\end{gather}` | Display | High |
| 1 | `\begin{multline}...\end{multline}` | Display | High |
| 2 | `\[...\]` | Display | High |
| 3 | `$$...$$` | Display | Medium (deprecated but common) |
| 4 | `\(...\)` | Inline | High |
| 5 | `$...$` | Inline | Low (currency ambiguity) |

### Recommended Extraction Strategy

**Multi-pass with occupied-span tracking:**
1. Pass 1: Named environments (equation, align, gather, multline, etc.)
2. Pass 2: `\[...\]` display math
3. Pass 3: `$$...$$` display math
4. Pass 4: `\(...\)` inline math
5. Pass 5: `$...$` inline math (lowest priority)

Each pass marks character spans as "occupied" to prevent overlapping matches.

### Edge Cases

| Case | Solution |
|------|----------|
| Escaped `\$` | Negative lookbehind `(?<!\\)` |
| `$$` vs `$` | Match `$$` first (Pass 3 before Pass 5) |
| Multi-line | `re.DOTALL` flag |
| Nested braces | Not a problem (braces aren't delimiters) |
| Currency `$` | "No space after opening $" rule + post-filter |
| Empty math `$$` | Require at least 1 non-space character |

### Libraries

| Library | Approach | Recommendation |
|---------|----------|---------------|
| `re` (stdlib) | Regex | **Primary** — zero deps, handles 95% of papers |
| `pylatexenc` | AST parser | **Fallback** — robust but ~10x slower |

### Post-Extraction Filtering

- Deduplicate by `latex_hash` (SHA-256, already in Formula model)
- Discard trivially short formulas (single variable `$x$`)
- Minimum complexity filter (e.g., must contain at least one LaTeX command `\`)

---

## 4. arXiv PDF Download Patterns

### URL Construction

```python
# New-style (2007+): https://export.arxiv.org/pdf/{YYMM.NNNNN}
# Old-style (pre-2007): https://export.arxiv.org/pdf/{archive}/{YYMMNNN}
# Version: append vN for specific version

def arxiv_id_to_pdf_url(arxiv_id: str) -> str:
    return f"https://export.arxiv.org/pdf/{arxiv_id}"
```

### Rate Limiting

| Context | Limit |
|---------|-------|
| API metadata queries | 1 req/3s, single connection |
| PDF downloads | Conservative 1 req/3s recommended |
| robots.txt Crawl-delay | 15s (for generic bots) |

**Critical**: Use `export.arxiv.org` (NOT `arxiv.org`) for programmatic access.

### Existing Codebase Integration

- `Paper.pdf_url` already populated by Discovery service
- `Paper.arxiv_id` available as fallback for URL construction
- `requests` already in project dependencies
- `urllib3.Retry` available for exponential backoff

### Download Strategy

- Use `requests.Session` with `HTTPAdapter` + `urllib3.Retry`
- Exponential backoff: 2s, 4s, 8s on 429/500/502/503/504
- Check `Content-Type: application/pdf` header
- Skip if file already exists and size > 1KB
- User-Agent: `ResearchPipeline/1.0 (mailto:gptprojectmanager@gmail.com)`
- Store PDFs in `data/pdfs/{arxiv_id}.pdf`

---

## Design Implications for Phase 12

1. **No schema changes needed**: `papers` and `formulas` tables already support the Extractor
2. **Three modules**: `pdf.py` (download), `rag_client.py` (RAGAnything), `latex.py` (regex extraction)
3. **Async polling pattern**: Submit to RAGAnything → poll `/jobs/{id}` → extract formulas from markdown
4. **RAGAnything markdown output** is the input for LaTeX regex — no direct PDF parsing needed
5. **Service port**: 8772 (per ARCHITECTURE.md)
6. **Follows established pattern**: `main.py` + handler classes + `@route` decorator
