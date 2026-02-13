# Analyzer Service — Design Specification

**Phase:** 08 (Research & Design)
**Date:** 2026-02-13
**Implements for:** Phase 9 (Analyzer Implementation)

## 1. Architecture Overview

```
                          ┌─────────────────────┐
                          │   Analyzer Service   │
                          │     Port: 8771       │
                          └──────────┬──────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ↓                ↓                ↓
             ┌──────────┐    ┌──────────┐    ┌──────────┐
             │ Gemini   │    │ Gemini   │    │ Ollama   │
             │ CLI      │    │ SDK      │    │ Local    │
             │ (primary)│    │ (backup) │    │ (local)  │
             └──────────┘    └──────────┘    └──────────┘
                    ↓                ↓                ↓
                    └────────────────┼────────────────┘
                                     ↓
                          ┌─────────────────────┐
                          │   SQLite DB (WAL)   │
                          │   papers.stage      │
                          │   papers.score      │
                          │   papers.prompt_ver │
                          └─────────────────────┘
```

**Data flow:**
1. Read papers with `stage='discovered'` from DB
2. For each paper: build scoring prompt from title + abstract
3. Call LLM via fallback chain (Gemini CLI → SDK → Ollama)
4. Parse JSON response, validate 5 scores (0.0-1.0)
5. Compute overall = mean(5 scores)
6. Update DB: `stage='analyzed'` (score >= 0.7) or `stage='rejected'` (score < 0.7)

## 2. File Structure

```
services/
└── analyzer/
    ├── __init__.py       # Empty
    ├── main.py           # AnalyzerHandler + main()
    ├── llm.py            # call_gemini_cli, call_gemini_sdk, call_ollama, fallback_chain
    └── prompt.py         # PROMPT_VERSION, SCORING_SYSTEM_PROMPT, format_scoring_prompt()
```

## 3. Schema Migration

### 3a. New column: prompt_version

```sql
ALTER TABLE papers ADD COLUMN prompt_version TEXT;
CREATE INDEX IF NOT EXISTS idx_papers_prompt_version ON papers(prompt_version);
```

**Migration strategy:** Idempotent check at service startup:

```python
def migrate_db(db_path: str) -> None:
    """Add prompt_version column if missing. Idempotent."""
    with transaction(db_path) as conn:
        # Check if column exists
        cursor = conn.execute("PRAGMA table_info(papers)")
        columns = {row[1] for row in cursor.fetchall()}
        if "prompt_version" not in columns:
            conn.execute("ALTER TABLE papers ADD COLUMN prompt_version TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_papers_prompt_version ON papers(prompt_version)"
            )
            logger.info("Migration: added prompt_version column to papers")
```

### 3b. New enum value: REJECTED

Add `REJECTED = "rejected"` to `PipelineStage` in `shared/models.py`:

```python
class PipelineStage(str, Enum):
    DISCOVERED = "discovered"
    ANALYZED = "analyzed"
    REJECTED = "rejected"     # ← NEW: below threshold, not processed further
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    CODEGEN = "codegen"
    COMPLETE = "complete"
    FAILED = "failed"
```

**Rationale:** `FAILED` = error/crash, `REJECTED` = deliberate below-threshold filtering.

## 4. Scoring Prompt

### 4a. System Prompt

```
You are an academic paper relevance scorer for Kelly criterion research.

You evaluate papers on 5 criteria, each scored from 0.0 to 1.0:

1. kelly_relevance: How relevant is this paper to the Kelly criterion, optimal bet sizing, fractional Kelly, portfolio allocation, or bankroll management?
2. mathematical_rigor: Does the paper contain formal mathematical content — proofs, derivations, theorems, lemmas, or significant mathematical notation?
3. novelty: Does the paper make an original contribution beyond the existing Kelly criterion literature? Is there a new insight, method, or extension?
4. practical_applicability: Does the paper provide practical implementation guidance — real-world data, backtests, code, algorithms, or actionable strategies?
5. data_quality: What is the quality of the methodology — dataset size, experimental design, reproducibility, statistical rigor?

Respond ONLY with valid JSON matching this exact schema:
{
  "scores": {
    "kelly_relevance": <float 0.0-1.0>,
    "mathematical_rigor": <float 0.0-1.0>,
    "novelty": <float 0.0-1.0>,
    "practical_applicability": <float 0.0-1.0>,
    "data_quality": <float 0.0-1.0>
  },
  "reasoning": "<1-2 sentence explanation>"
}

Do not include markdown fences, comments, or any text outside the JSON object.
If the abstract is missing or very short (under 50 characters), note this limitation in reasoning and score conservatively.
```

### 4b. User Prompt Template

```python
PROMPT_VERSION = "v1"

def format_scoring_prompt(title: str, abstract: str | None,
                          authors: list[str], categories: list[str]) -> str:
    """Build the user prompt for LLM paper scoring."""
    authors_str = ", ".join(authors[:5])  # Limit to 5 to save tokens
    if len(authors) > 5:
        authors_str += f" et al. ({len(authors)} total)"
    categories_str = ", ".join(categories)

    abstract_text = abstract if abstract and len(abstract) >= 50 else "(abstract not available)"

    return (
        f"Score this academic paper:\n\n"
        f"Title: {title}\n"
        f"Authors: {authors_str}\n"
        f"Categories: {categories_str}\n\n"
        f"Abstract:\n{abstract_text}"
    )
```

### 4c. LLM Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| temperature | 0.3 | Low for reproducibility |
| max_output_tokens | 500 | JSON response ~200 tokens, buffer for reasoning |
| model | gemini-2.5-flash / qwen3:8b | Fast, cheap, sufficient for classification |
| format | JSON | Structured output |

## 5. LLM Client Functions

### 5a. call_gemini_cli

```python
def call_gemini_cli(prompt: str, system: str,
                    model: str = "gemini-2.5-flash",
                    timeout: int = 120) -> str:
    """Call Gemini via CLI subprocess.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Gemini model name.
        timeout: Subprocess timeout in seconds.

    Returns:
        Raw response text from Gemini.

    Raises:
        RuntimeError: On non-zero exit, API error, or timeout.
    """
    # Build full prompt with system instruction prefix
    full_prompt = f"{system}\n\n---\n\n{prompt}"

    result = subprocess.run(
        ["gemini", "-p", full_prompt, "-m", model,
         "--output-format", "json", "-e", "none"],
        capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GOOGLE_API_KEY": _get_gemini_api_key()},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI exit {result.returncode}: {result.stderr[:200]}")

    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError(f"Gemini API error: {data['error'].get('message', 'unknown')}")

    response_text = data.get("response", "")
    # Strip markdown fences (GitHub #11184)
    return _strip_markdown_fences(response_text)
```

### 5b. call_gemini_sdk

```python
def call_gemini_sdk(prompt: str, system: str,
                    model: str = "gemini-2.5-flash",
                    timeout: float = 30.0) -> str:
    """Call Gemini via Python SDK.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Gemini model name.
        timeout: HTTP timeout in seconds.

    Returns:
        Raw response text from Gemini SDK.

    Raises:
        RuntimeError: On API error or timeout.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=_get_gemini_api_key(),
        http_options=types.HttpOptions(client_args={"timeout": timeout}),
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
            max_output_tokens=500,
            response_mime_type="application/json",
        ),
    )
    return response.text
```

### 5c. call_ollama

```python
def call_ollama(prompt: str, system: str,
                model: str = "qwen3:8b",
                timeout: int = 120,
                base_url: str = "http://localhost:11434") -> str:
    """Call Ollama local LLM.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Ollama model name.
        timeout: HTTP timeout in seconds.
        base_url: Ollama server URL.

    Returns:
        Raw response text from Ollama.

    Raises:
        RuntimeError: On connection error, timeout, or non-200 response.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": system,
        "format": "json",
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.3, "num_predict": 500},
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status}")
        data = json.loads(resp.read())

    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    return data["response"]
```

### 5d. fallback_chain

```python
def fallback_chain(prompt: str, system: str) -> tuple[str, str]:
    """Try LLM providers in order: Gemini CLI → Gemini SDK → Ollama.

    Args:
        prompt: User prompt text.
        system: System instruction text.

    Returns:
        Tuple of (response_text, provider_name).

    Raises:
        RuntimeError: If all 3 providers fail.
    """
    providers = [
        ("gemini_cli", call_gemini_cli),
        ("gemini_sdk", call_gemini_sdk),
        ("ollama", call_ollama),
    ]
    errors = []
    for name, func in providers:
        try:
            result = func(prompt, system)
            return (result, name)
        except Exception as e:
            logger.warning("LLM fallback: %s failed: %s", name, e)
            errors.append(f"{name}: {e}")

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
```

### 5e. Helper: _get_gemini_api_key

```python
def _get_gemini_api_key() -> str:
    """Load Gemini API key from environment.

    Returns:
        API key string.

    Raises:
        RuntimeError: If key not found.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return key
```

### 5f. Helper: _strip_markdown_fences

```python
import re

def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM response."""
    # Strip ```json ... ``` or ``` ... ```
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()
```

## 6. AnalyzerHandler

### 6a. Class Structure

```python
class AnalyzerHandler(BaseHandler):
    """HTTP handler for the Analyzer service."""

    threshold: float = 0.7
    max_papers_default: int = 10

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        """Analyze discovered papers with LLM scoring."""
        ...
```

### 6b. /process Flow

```
1. Parse request
   - paper_id: Optional[int] — analyze specific paper
   - max_papers: int = 10 — batch limit
   - force: bool = False — reprocess already scored papers

2. Query papers
   IF paper_id:
     SELECT * FROM papers WHERE id=? AND (stage='discovered' OR (force AND stage IN ('analyzed','rejected')))
   ELSE:
     SELECT * FROM papers WHERE stage='discovered' ORDER BY created_at ASC LIMIT ?

3. For each paper:
   a. Check abstract
      IF title is empty/None → skip, add error "missing_title"
      IF abstract is None or len(abstract) < 50 → set low_abstract=True

   b. Build prompt
      prompt = format_scoring_prompt(title, abstract, authors, categories)

   c. Call LLM
      response_text, provider = fallback_chain(prompt, SCORING_SYSTEM_PROMPT)

   d. Parse response
      TRY:
        scores_data = json.loads(response_text)
      EXCEPT JSONDecodeError:
        # Retry with stricter suffix
        retry_prompt = prompt + "\n\nRespond ONLY with valid JSON, no markdown fences, no extra text."
        response_text, provider = fallback_chain(retry_prompt, SCORING_SYSTEM_PROMPT)
        scores_data = json.loads(response_text)  # If still fails → skip paper

   e. Validate scores
      EXPECTED_KEYS = {"kelly_relevance", "mathematical_rigor", "novelty",
                       "practical_applicability", "data_quality"}
      scores = scores_data.get("scores", {})
      IF set(scores.keys()) != EXPECTED_KEYS → skip, add error "invalid_score_keys"

      clamped = False
      FOR key in EXPECTED_KEYS:
        val = float(scores[key])
        IF val < 0.0 or val > 1.0:
          logger.warning("Score %s=%f out of range for paper %d, clamping", key, val, paper_id)
          scores[key] = max(0.0, min(1.0, val))
          clamped = True

   f. Compute overall
      overall = sum(scores.values()) / 5

   g. Determine stage
      IF overall >= threshold → new_stage = 'analyzed'
      ELSE → new_stage = 'rejected'

   h. Update DB
      UPDATE papers SET
        stage=new_stage,
        score=overall,
        prompt_version=PROMPT_VERSION,
        error=('score_clamped' IF clamped ELSE NULL),
        updated_at=datetime('now')
      WHERE id=paper_id

4. Return summary
   {
     "papers_analyzed": total_count,
     "papers_accepted": accepted_count,
     "papers_rejected": rejected_count,
     "avg_score": avg_overall,
     "llm_provider": last_provider,
     "prompt_version": PROMPT_VERSION,
     "errors": [...],
     "time_ms": elapsed
   }
```

### 6c. /process Request/Response

**Request:**
```json
{
  "paper_id": 42,
  "max_papers": 10,
  "force": false
}
```
All fields optional. Defaults: no paper_id (batch), max_papers=10, force=false.

**Response (success):**
```json
{
  "papers_analyzed": 5,
  "papers_accepted": 2,
  "papers_rejected": 3,
  "avg_score": 0.58,
  "llm_provider": "gemini_cli",
  "prompt_version": "v1",
  "errors": [],
  "time_ms": 15234
}
```

**Response (partial errors):**
```json
{
  "papers_analyzed": 3,
  "papers_accepted": 1,
  "papers_rejected": 2,
  "avg_score": 0.52,
  "llm_provider": "ollama",
  "prompt_version": "v1",
  "errors": [
    "paper 42: all LLM providers failed",
    "paper 57: invalid JSON after retry"
  ],
  "time_ms": 45678
}
```

## 7. Configuration

### 7a. Environment Variables

| Env Var | Default | Purpose |
|---------|---------|---------|
| `RP_ANALYZER_PORT` | 8771 | Service port |
| `RP_ANALYZER_THRESHOLD` | 0.7 | Score threshold |
| `RP_ANALYZER_MAX_PAPERS` | 10 | Default batch size |
| `RP_ANALYZER_GEMINI_MODEL` | gemini-2.5-flash | Gemini model |
| `RP_ANALYZER_OLLAMA_URL` | http://localhost:11434 | Ollama endpoint |
| `RP_ANALYZER_OLLAMA_MODEL` | qwen3:8b | Ollama model |
| `GEMINI_API_KEY` | (required) | Gemini API key (from SSOT via dotenvx) |
| `RP_DB_PATH` | ./data/research.db | SQLite database |
| `RP_LOG_LEVEL` | INFO | Log level |

### 7b. Config Loading

The existing `shared/config.py` handles port, db_path, log_level, data_dir. Service-specific vars (THRESHOLD, GEMINI_MODEL, etc.) are loaded directly in `main.py` via `os.environ.get()`.

**No changes needed to shared/config.py** — analyzer-specific config is simple enough to read inline.

## 8. Dependencies

### 8a. New pip dependency

```toml
# pyproject.toml — add to dependencies
"google-genai>=1.0",
```

### 8b. External services

| Service | URL | Required |
|---------|-----|----------|
| Gemini API | via CLI / SDK | Optional (fallback exists) |
| Ollama | http://localhost:11434 | Required (last resort) |
| SQLite DB | local file | Required |

## 9. Error Handling Matrix

| Error | Source | Action |
|-------|--------|--------|
| Gemini CLI timeout | subprocess | Log warning, try SDK |
| Gemini CLI auth error | exit code 41 | Log warning, try SDK |
| Gemini SDK 429 | rate limit | Log warning, try Ollama |
| Gemini SDK APIError | various | Log warning, try Ollama |
| Ollama connection refused | network | Log error, skip paper |
| Ollama 404 | model not found | Log error, skip paper |
| All providers fail | cascade | Skip paper, add to errors list |
| Invalid JSON | LLM output | Retry once with strict suffix, then skip |
| Missing score keys | LLM output | Skip paper, add to errors list |
| Score out of range | LLM output | Clamp + warn + flag in error field |
| Missing title | DB data | Skip paper immediately |
| Missing abstract | DB data | Score with note, mark low confidence |
| DB error | SQLite | Raise, let BaseHandler return 500 |

## 10. Service Startup

```python
def main() -> None:
    config = load_config("analyzer")
    init_db(config.db_path)
    migrate_db(str(config.db_path))  # Add prompt_version column

    # Load analyzer-specific config
    AnalyzerHandler.threshold = float(
        os.environ.get("RP_ANALYZER_THRESHOLD", "0.7"))
    AnalyzerHandler.max_papers_default = int(
        os.environ.get("RP_ANALYZER_MAX_PAPERS", "10"))

    service = BaseService("analyzer", config.port, AnalyzerHandler, str(config.db_path))
    service.run()

if __name__ == "__main__":
    main()
```

## 11. Acceptance Criteria for Phase 9

- [ ] `services/analyzer/main.py` — AnalyzerHandler with /process endpoint
- [ ] `services/analyzer/llm.py` — 3 client functions + fallback_chain
- [ ] `services/analyzer/prompt.py` — scoring prompt template (v1)
- [ ] `shared/models.py` — REJECTED stage added to PipelineStage
- [ ] Schema migration runs at startup (prompt_version column)
- [ ] `google-genai` added to pyproject.toml
- [ ] Health/status endpoints work
- [ ] Manual test: analyze 1 paper via /process
