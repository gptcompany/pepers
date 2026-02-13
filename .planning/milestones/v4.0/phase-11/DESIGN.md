# Extractor Service Design Specification

> Phase 11 deliverable. Phase 12 implements directly from this document.

## Overview

The Extractor service is the third microservice in the research pipeline. It reads papers with `stage='analyzed'`, downloads their PDFs from arXiv, sends them to RAGAnything for text extraction, parses LaTeX formulas from the resulting markdown, and stores formulas in the `formulas` table.

**Port:** 8772
**Entry point:** `python -m services.extractor.main`

## Architecture

```
                      ┌─────────────────────────┐
                      │   Extractor (:8772)      │
                      │                          │
POST /process ───────►│  main.py                 │
                      │    │                     │
                      │    ├── pdf.py             │
                      │    │   └── download_pdf() ─────► export.arxiv.org
                      │    │                     │
                      │    ├── rag_client.py      │
                      │    │   └── process_paper() ────► RAGAnything (:8767)
                      │    │                     │
                      │    └── latex.py           │
                      │        └── extract_formulas() → list[Formula]
                      │                          │
                      │  DB: papers → formulas   │
                      └─────────────────────────┘
```

## File Structure

```
services/extractor/
├── __init__.py          # Package init
├── main.py              # ExtractorHandler + service startup (~200 LOC)
├── pdf.py               # arXiv PDF download with retry (~80 LOC)
├── rag_client.py        # RAGAnything HTTP client (~120 LOC)
└── latex.py             # LaTeX regex extraction engine (~150 LOC)
```

Estimated: ~550 LOC total (comparable to Analyzer's 600 LOC).

## Data Flow

```
1. SELECT papers WHERE stage='analyzed' ORDER BY created_at ASC LIMIT N
   ↓
2. For each paper:
   a. download_pdf(paper) → data/pdfs/{arxiv_id}.pdf
   b. process_paper(pdf_path, arxiv_id) → markdown text
   c. extract_formulas(markdown) → raw formulas list
   d. filter_formulas(raw) → filtered formulas
   e. formulas_to_models(paper_id, markdown, filtered) → list[Formula]
   f. INSERT INTO formulas (deduplicate by latex_hash)
   g. UPDATE papers SET stage='extracted'
   ↓
3. Return summary: {papers_processed, formulas_extracted, errors}
```

---

## Module 1: pdf.py — PDF Download

### Constants

```python
EXPORT_BASE = "https://export.arxiv.org/pdf"
USER_AGENT = "ResearchPipeline/1.0 (academic-formula-extraction)"
DOWNLOAD_TIMEOUT = 60   # seconds per request
```

### Functions

#### `create_session() -> requests.Session`

Creates a reusable session with retry strategy.

```python
def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf",
    })
    retry = Retry(
        total=3,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
```

#### `get_pdf_url(paper: Paper) -> str`

Returns PDF URL, preferring stored `pdf_url`, falling back to constructed URL.

```python
def get_pdf_url(paper: Paper) -> str:
    if paper.pdf_url:
        # Rewrite to export domain if needed
        url = paper.pdf_url.replace("http://arxiv.org", "https://export.arxiv.org")
        url = url.replace("https://arxiv.org", "https://export.arxiv.org")
        return url
    return f"{EXPORT_BASE}/{paper.arxiv_id}"
```

#### `download_pdf(paper: Paper, dest_dir: Path, session: requests.Session | None = None) -> Path`

Downloads PDF to local filesystem. Skips if already cached.

```python
def download_pdf(
    paper: Paper, dest_dir: Path, session: requests.Session | None = None
) -> Path:
    if session is None:
        session = create_session()

    url = get_pdf_url(paper)
    safe_name = paper.arxiv_id.replace("/", "_")
    dest_path = dest_dir / f"{safe_name}.pdf"

    # Cache check
    if dest_path.exists() and dest_path.stat().st_size > 1000:
        return dest_path

    resp = session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
    resp.raise_for_status()

    # Validate content type
    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type:
        raise RuntimeError(f"Expected PDF, got {content_type} for {paper.arxiv_id}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return dest_path
```

---

## Module 2: rag_client.py — RAGAnything Client

### Constants

```python
DEFAULT_BASE_URL = "http://localhost:8767"
DEFAULT_POLL_INTERVAL = 10   # seconds
DEFAULT_TIMEOUT = 600        # seconds (10 min)
```

### Functions

#### `check_service(base_url: str) -> dict`

Checks RAGAnything availability and circuit breaker state.

```python
def check_service(base_url: str = DEFAULT_BASE_URL) -> dict:
    resp = urllib.request.urlopen(f"{base_url}/status", timeout=10)
    data = json.loads(resp.read().decode())

    if data.get("circuit_breaker", {}).get("state") == "open":
        raise RuntimeError("RAGAnything circuit breaker is open")

    return data
```

Uses `urllib.request` (stdlib) — no `requests` dependency for this module.

#### `submit_pdf(pdf_path: Path, paper_id: str, base_url: str) -> dict`

Submits PDF to RAGAnything for processing.

```python
def submit_pdf(
    pdf_path: Path, paper_id: str, base_url: str = DEFAULT_BASE_URL
) -> dict:
    payload = json.dumps({
        "pdf_path": str(pdf_path),
        "paper_id": paper_id,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/process",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode())

    # 200 = cached result
    if data.get("cached"):
        return {"cached": True, "result": data}

    # 202 = job queued
    return {"cached": False, "job_id": data["job_id"]}
```

#### `poll_job(job_id: str, base_url: str, timeout: float, interval: float) -> dict`

Polls job status until completion or timeout.

```python
def poll_job(
    job_id: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = urllib.request.urlopen(
            f"{base_url}/jobs/{job_id}", timeout=10
        )
        data = json.loads(resp.read().decode())

        if data["status"] == "completed":
            return data["result"]
        if data["status"] == "failed":
            raise RuntimeError(f"RAGAnything job {job_id} failed: {data.get('error')}")

        time.sleep(interval)

    raise TimeoutError(f"RAGAnything job {job_id} timed out after {timeout}s")
```

#### `read_markdown(output_dir: str) -> str`

Reads the markdown output from RAGAnything's extraction directory.

```python
def read_markdown(output_dir: str) -> str:
    # Handle container path mapping
    host_dir = output_dir.replace("/workspace/1TB/", "/media/sam/1TB/")
    host_dir = host_dir.replace("/workspace/3TB-WDC/", "/media/sam/3TB-WDC/")

    path = Path(host_dir)
    # RAGAnything stores markdown as auto_*.md or *.md
    md_files = list(path.glob("**/*.md"))
    if not md_files:
        raise FileNotFoundError(f"No markdown files in {host_dir}")

    # Read largest .md file (the main extraction output)
    md_files.sort(key=lambda f: f.stat().st_size, reverse=True)
    return md_files[0].read_text(encoding="utf-8")
```

#### `process_paper(pdf_path: Path, paper_id: str, base_url: str) -> str`

High-level orchestration function. Returns markdown text.

```python
def process_paper(
    pdf_path: Path, paper_id: str, base_url: str = DEFAULT_BASE_URL
) -> str:
    check_service(base_url)

    result = submit_pdf(pdf_path, paper_id, base_url)

    if result["cached"]:
        output_dir = result["result"].get("output_dir", "")
    else:
        job_result = poll_job(result["job_id"], base_url)
        output_dir = job_result.get("output_dir", "")

    if not output_dir:
        raise RuntimeError(f"No output_dir in RAGAnything result for {paper_id}")

    return read_markdown(output_dir)
```

---

## Module 3: latex.py — LaTeX Extraction Engine

### Constants

```python
import re

MATH_ENV_NAMES = (
    "equation", "align", "gather", "multline",
    "flalign", "eqnarray", "displaymath", "math",
    "aligned", "gathered",
)

MIN_FORMULA_LENGTH = 3
CONTEXT_WINDOW = 200
```

### Compiled Patterns (5, priority order)

```python
# Pass 1: Named math environments
PATTERN_NAMED_ENV = re.compile(
    r"\\begin\{(" + "|".join(MATH_ENV_NAMES) + r")\*?\}"
    r"(.*?)"
    r"\\end\{\1\*?\}",
    re.DOTALL,
)

# Pass 2: \[...\]
PATTERN_DISPLAY_BRACKET = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)

# Pass 3: $$...$$
PATTERN_DISPLAY_DOLLAR = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)

# Pass 4: \(...\)
PATTERN_INLINE_PAREN = re.compile(r"\\\((.*?)\\\)", re.DOTALL)

# Pass 5: $...$ (most ambiguous, lowest priority)
PATTERN_INLINE_DOLLAR = re.compile(
    r"(?<!\\)"     # not escaped \$
    r"(?<!\$)"     # not part of $$
    r"\$"
    r"(?!\$)"      # not $$
    r"(?!\s)"      # no leading space
    r"([^\$\n]+?)" # content (non-greedy, single line)
    r"(?<!\s)"     # no trailing space
    r"\$"
    r"(?!\$)",     # not $$
)
```

### Functions

#### `extract_formulas(text: str) -> list[dict]`

Multi-pass extraction with occupied-span tracking.

```python
def extract_formulas(text: str) -> list[dict]:
    formulas = []
    occupied: set[int] = set()

    def _add(latex: str, ftype: str, start: int, end: int):
        span = set(range(start, end))
        if not span & occupied:
            occupied.update(span)
            formulas.append({
                "latex": latex.strip(),
                "formula_type": ftype,
                "start": start,
                "end": end,
            })

    # Pass 1: Named environments
    for m in PATTERN_NAMED_ENV.finditer(text):
        _add(m.group(2), "display" if m.group(1) != "math" else "inline",
             m.start(), m.end())

    # Pass 2: \[...\]
    for m in PATTERN_DISPLAY_BRACKET.finditer(text):
        _add(m.group(1), "display", m.start(), m.end())

    # Pass 3: $$...$$
    for m in PATTERN_DISPLAY_DOLLAR.finditer(text):
        _add(m.group(1), "display", m.start(), m.end())

    # Pass 4: \(...\)
    for m in PATTERN_INLINE_PAREN.finditer(text):
        _add(m.group(1), "inline", m.start(), m.end())

    # Pass 5: $...$
    for m in PATTERN_INLINE_DOLLAR.finditer(text):
        _add(m.group(1), "inline", m.start(), m.end())

    formulas.sort(key=lambda f: f["start"])
    return formulas
```

#### `extract_context(text: str, start: int, end: int, window: int = CONTEXT_WINDOW) -> str`

Extracts surrounding text for a formula.

```python
def extract_context(
    text: str, start: int, end: int, window: int = CONTEXT_WINDOW
) -> str:
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].strip()
```

#### `filter_formulas(formulas: list[dict]) -> list[dict]`

Removes trivial and duplicate formulas.

```python
def filter_formulas(formulas: list[dict]) -> list[dict]:
    seen_hashes: set[str] = set()
    filtered = []

    for f in formulas:
        latex = f["latex"]

        # Skip trivially short
        if len(latex.strip()) < MIN_FORMULA_LENGTH:
            continue

        # Skip non-math (no LaTeX commands)
        if "\\" not in latex and "{" not in latex:
            continue

        # Deduplicate by hash
        h = hashlib.sha256(latex.encode()).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        filtered.append(f)

    return filtered
```

#### `formulas_to_models(paper_id: int, text: str, raw_formulas: list[dict]) -> list[Formula]`

Converts extracted formulas to Pydantic models.

```python
def formulas_to_models(
    paper_id: int, text: str, raw_formulas: list[dict]
) -> list[Formula]:
    return [
        Formula(
            paper_id=paper_id,
            latex=f["latex"],
            formula_type=f["formula_type"],
            context=extract_context(text, f["start"], f["end"]),
        )
        for f in raw_formulas
    ]
```

---

## Module 4: main.py — Service Handler

### ExtractorHandler

```python
class ExtractorHandler(BaseHandler):
    max_papers_default: int = 10
    pdf_dir: str = "data/pdfs"
    rag_url: str = "http://localhost:8767"
    download_delay: float = 3.0

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        start = time.time()

        paper_id = data.get("paper_id")
        max_papers = data.get("max_papers", self.max_papers_default)
        force = data.get("force", False)

        papers = _query_papers(self.db_path, paper_id, max_papers, force)
        if not papers:
            return {
                "success": True,
                "service": "extractor",
                "papers_processed": 0,
                "formulas_extracted": 0,
                "errors": [],
                "time_ms": int((time.time() - start) * 1000),
            }

        # Check RAGAnything before starting batch
        try:
            rag_client.check_service(self.rag_url)
        except RuntimeError as e:
            self.send_error_json(str(e), "SERVICE_UNAVAILABLE", 503)
            return None

        session = pdf.create_session()
        errors = []
        total_formulas = 0
        papers_ok = 0

        for i, paper_row in enumerate(papers):
            pid = paper_row["id"]
            paper = Paper(**paper_row)

            try:
                # Step 1: Download PDF
                pdf_path = pdf.download_pdf(
                    paper, Path(self.pdf_dir), session
                )

                # Step 2: RAGAnything processing
                markdown = rag_client.process_paper(
                    pdf_path, paper.arxiv_id, self.rag_url
                )

                # Step 3: Extract formulas
                raw = latex.extract_formulas(markdown)
                filtered = latex.filter_formulas(raw)
                formulas = latex.formulas_to_models(pid, markdown, filtered)

                # Step 4: Store formulas + update paper
                _store_results(self.db_path, pid, formulas)
                total_formulas += len(formulas)
                papers_ok += 1

            except Exception as e:
                logger.error("Failed paper %d: %s", pid, e)
                errors.append(f"paper {pid}: {e}")
                _mark_failed(self.db_path, pid, str(e))

            # Rate limit between papers
            if i < len(papers) - 1:
                time.sleep(self.download_delay)

        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "success": True,
            "service": "extractor",
            "papers_processed": papers_ok,
            "formulas_extracted": total_formulas,
            "papers_failed": len(errors),
            "errors": errors,
            "time_ms": elapsed_ms,
        }
```

### Helper Functions

```python
def _query_papers(db_path, paper_id, max_papers, force) -> list:
    """Query papers with stage='analyzed' (or specific paper_id with force)."""
    with transaction(db_path) as conn:
        if paper_id is not None:
            if force:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? "
                    "AND stage IN ('analyzed', 'extracted', 'failed')",
                    (paper_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? AND stage='analyzed'",
                    (paper_id,),
                )
        else:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE stage='analyzed' "
                "ORDER BY created_at ASC LIMIT ?",
                (max_papers,),
            )
        return [dict(row) for row in cursor.fetchall()]


def _store_results(db_path, paper_id, formulas: list[Formula]) -> None:
    """Insert formulas and update paper stage."""
    with transaction(db_path) as conn:
        for f in formulas:
            # Deduplicate: skip if latex_hash already exists for this paper
            existing = conn.execute(
                "SELECT id FROM formulas WHERE paper_id=? AND latex_hash=?",
                (paper_id, f.latex_hash),
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, "
                "description, formula_type, context, stage, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f.paper_id, f.latex, f.latex_hash,
                    f.description, f.formula_type, f.context,
                    f.stage.value, f.error,
                ),
            )

        conn.execute(
            "UPDATE papers SET stage='extracted', updated_at=datetime('now') "
            "WHERE id=?",
            (paper_id,),
        )


def _mark_failed(db_path, paper_id, error: str) -> None:
    """Mark paper as failed with error message."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE papers SET stage='failed', error=?, "
            "updated_at=datetime('now') WHERE id=?",
            (f"extractor: {error}", paper_id),
        )
```

### Service Startup

```python
def main() -> None:
    config = load_config("extractor")
    init_db(config.db_path)

    ExtractorHandler.max_papers_default = int(
        os.environ.get("RP_EXTRACTOR_MAX_PAPERS", "10")
    )
    ExtractorHandler.pdf_dir = os.environ.get("RP_EXTRACTOR_PDF_DIR", "data/pdfs")
    ExtractorHandler.rag_url = os.environ.get(
        "RP_EXTRACTOR_RAG_URL", "http://localhost:8767"
    )
    ExtractorHandler.download_delay = float(
        os.environ.get("RP_EXTRACTOR_DOWNLOAD_DELAY", "3.0")
    )

    service = BaseService("extractor", config.port, ExtractorHandler, str(config.db_path))
    service.run()
```

---

## Configuration Reference

| Env Var | Default | Purpose |
|---------|---------|---------|
| `RP_EXTRACTOR_PORT` | `8772` | Service port |
| `RP_EXTRACTOR_MAX_PAPERS` | `10` | Default batch size |
| `RP_EXTRACTOR_PDF_DIR` | `data/pdfs` | PDF storage directory |
| `RP_EXTRACTOR_DOWNLOAD_DELAY` | `3.0` | Seconds between arXiv downloads |
| `RP_EXTRACTOR_RAG_URL` | `http://localhost:8767` | RAGAnything base URL |
| `RP_EXTRACTOR_RAG_TIMEOUT` | `600` | Max wait for RAGAnything (seconds) |
| `RP_EXTRACTOR_RAG_POLL_INTERVAL` | `10` | Poll interval (seconds) |
| `RP_EXTRACTOR_MIN_FORMULA_LENGTH` | `3` | Minimum LaTeX formula length |
| `RP_EXTRACTOR_CONTEXT_WINDOW` | `200` | Characters of context around formula |
| `RP_DB_PATH` | `data/research.db` | SQLite database path |
| `RP_LOG_LEVEL` | `INFO` | Log level |

**No secrets needed** — RAGAnything and arXiv are unauthenticated.

---

## Error Handling Matrix

| Error | Stage Change | Error Field | Batch Behavior |
|-------|-------------|-------------|----------------|
| PDF download 404 | `failed` | `extractor: pdf_download: 404` | Continue next paper |
| PDF download timeout | `failed` | `extractor: pdf_download: timeout` | Continue |
| RAGAnything circuit breaker open | (no change) | (none) | **Abort batch**, return 503 |
| RAGAnything job timeout | `failed` | `extractor: raganything_timeout` | Continue |
| RAGAnything job failed | `failed` | `extractor: raganything_error: {msg}` | Continue |
| No markdown output | `failed` | `extractor: no_markdown_output` | Continue |
| 0 formulas extracted | `extracted` | (none) | Continue (paper has no math) |
| DB insert error | `failed` | `extractor: db_insert: {err}` | Continue |

---

## Schema

**No schema changes needed.** The existing tables from v1.0 support the Extractor:

```sql
-- Already exists in shared/db.py
CREATE TABLE IF NOT EXISTS formulas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    latex TEXT NOT NULL,
    latex_hash TEXT NOT NULL,
    description TEXT,
    formula_type TEXT,
    context TEXT,
    stage TEXT NOT NULL DEFAULT 'extracted',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Existing indexes
CREATE INDEX IF NOT EXISTS idx_formulas_paper_id ON formulas(paper_id);
CREATE INDEX IF NOT EXISTS idx_formulas_latex_hash ON formulas(latex_hash);
```

---

## Dependencies

**No new dependencies.** All required packages are already in the project:
- `requests` (with `urllib3`) — PDF download
- `urllib.request` (stdlib) — RAGAnything client
- `re` (stdlib) — LaTeX regex
- `hashlib` (stdlib) — Formula deduplication
- `pydantic` — Formula model validation

---

## Integration Testing Strategy (for Phase 13)

| Test Type | What | Mock |
|-----------|------|------|
| Unit: `pdf.py` | URL construction, cache check | `requests.Session` |
| Unit: `latex.py` | All 5 regex passes, edge cases, filtering | None (pure functions) |
| Unit: `rag_client.py` | Submit, poll, path mapping | `urllib.request.urlopen` |
| Integration | Full pipeline with real SQLite | RAGAnything (mock HTTP) |
| E2E | Real RAGAnything + sample PDF | None (real services) |
