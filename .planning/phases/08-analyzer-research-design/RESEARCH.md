# Phase 8: Analyzer Research & Design — Research Findings

**Date:** 2026-02-12
**Status:** Complete (API research done, design decisions pending)

## 1. Gemini CLI (Primary LLM)

**Invocation:**
```bash
gemini -p "prompt text" --output-format json -m gemini-2.5-flash
```

**Key flags:**
| Flag | Purpose |
|------|---------|
| `-p`, `--prompt` | Headless mode (non-interactive) |
| `--output-format` | `text` (default), `json`, `stream-json` |
| `-m`, `--model` | Model selection (e.g., `gemini-2.5-flash`) |
| `-y`, `--yolo` | Auto-approve all tool actions |
| `--approval-mode` | `default`, `auto_edit`, `yolo` |

**JSON response schema:**
```json
{
  "response": "string",
  "stats": {
    "models": {
      "[model-name]": {
        "api": {"totalRequests": 0, "totalErrors": 0, "totalLatencyMs": 0},
        "tokens": {"prompt": 0, "candidates": 0, "total": 0, "cached": 0}
      }
    },
    "tools": {"totalCalls": 0, "totalSuccess": 0, "totalFail": 0},
    "files": {"totalLinesAdded": 0, "totalLinesRemoved": 0}
  },
  "error": {"type": "string", "message": "string", "code": 0}
}
```

**Authentication:**
- OAuth (Google account) — uses subscription quota (1000 RPD, 60 RPM)
- API key — free tier (250 RPD, 10 RPM, Flash only)
- Vertex AI ADC

**Rate limits (OAuth - subscription):**
- 1000 requests/user/day
- 60 requests/user/minute

**Subprocess gotchas:**
- **MUST use `stdin=subprocess.DEVNULL`** — hangs indefinitely without it (GitHub #6715)
- **MUST use `GOOGLE_API_KEY` env var** — OAuth hangs/prompts browser in subprocess (GitHub #12042)
- **Use `-e none`** — disables extensions/MCP for pure LLM usage (faster, safer)
- No `--timeout` flag exists — use `subprocess.run(timeout=N)` in Python
- Non-interactive mode blocks tool authorization (safer for our use case)
- Exit code 0 = success, non-zero = error (41 for auth errors proposed)
- JSON `response` field may contain markdown fences (`` ```json...``` ``) — strip them (GitHub #11184)
- Auto fallback: Pro → Flash on rate limit. Disable with `"fallbackEnabled": false` in settings.json

**Recommended Python pattern:**
```python
def call_gemini(prompt: str, model: str = "gemini-2.5-flash", timeout: int = 120) -> dict:
    result = subprocess.run(
        ["gemini", "-p", prompt, "-m", model, "--output-format", "json", "-e", "none"],
        capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GOOGLE_API_KEY": api_key},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI failed (exit {result.returncode}): {result.stderr}")
    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError(f"Gemini API error: {data['error'].get('message')}")
    return data
```

**Known issues:**
- OAuth quota sometimes not recognized (shows free tier limits)
- "Usage limit reached" even when stats show capacity — workaround: switch to API key
- Can hang if model calls tools requiring approval (GitHub #12337) — use `-e none`

## 2. Gemini SDK (Secondary LLM)

**Package:** `pip install google-genai` (NOT `google-generativeai` — deprecated, EOL Nov 2025)

**Basic usage:**
```python
from google import genai
from google.genai import types, errors

client = genai.Client(api_key='GEMINI_API_KEY')

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='Score this paper...',
    config=types.GenerateContentConfig(
        system_instruction='You are an academic paper scorer...',
        temperature=0.3,
        max_output_tokens=500,
        response_mime_type='application/json',
    ),
)
print(response.text)  # JSON string
```

**JSON output:** Set `response_mime_type='application/json'` in GenerateContentConfig

**Error handling:**
```python
from google.genai import errors

try:
    response = client.models.generate_content(...)
except errors.APIError as e:
    print(e.code)     # HTTP status code (404, 429, 500, etc.)
    print(e.message)  # Human-readable error
```

**Timeout:**
```python
client = genai.Client(
    api_key='KEY',
    http_options=types.HttpOptions(
        client_args={'timeout': 30.0}  # seconds
    )
)
```

**Rate limits (free tier):**
| Model | RPM | TPM | RPD |
|-------|-----|-----|-----|
| `gemini-2.5-pro` | 5 | 250,000 | 100 |
| `gemini-2.5-flash` | 10 | 250,000 | 250 |
| `gemini-2.5-flash-lite` | 15 | 250,000 | 1,000 |

**429 handling:** Catch `google.api_core.exceptions.ResourceExhausted`

**Models available:** `gemini-2.5-flash` (best quality/limit ratio), `gemini-2.5-flash-lite` (1000 RPD), `gemini-2.5-pro`
**Note:** `gemini-2.0-flash` retiring March 31, 2026 — use 2.5 variants

## 3. Ollama API (Tertiary/Local LLM)

**Base URL:** `http://localhost:11434`

**Generate endpoint:**
```
POST /api/generate
```

**Request body:**
```json
{
  "model": "qwen3:8b",
  "prompt": "Score this paper...",
  "system": "You are an academic paper scorer...",
  "format": "json",
  "stream": false,
  "keep_alive": "10m",
  "options": {
    "temperature": 0.3,
    "top_p": 0.95,
    "num_predict": 500
  }
}
```

**Response (non-streaming):**
```json
{
  "model": "qwen3:8b",
  "created_at": "2026-02-12T...",
  "response": "{...json string...}",
  "done": true,
  "total_duration": 5000000000,
  "load_duration": 1000000000,
  "prompt_eval_count": 150,
  "prompt_eval_duration": 500000000,
  "eval_count": 100,
  "eval_duration": 3000000000
}
```

**JSON mode:** `"format": "json"` — forces valid JSON output. Also supports JSON schema object for structured output.

**Health check endpoints:**
| Endpoint | Purpose |
|----------|---------|
| `GET /` | Basic health (returns "Ollama is running") |
| `GET /api/tags` | List local models (validates availability) |
| `GET /api/version` | API version check |

**Error handling:**
| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Malformed request |
| 404 | Model not found |
| 429 | Rate limit |
| 500 | Server error |
| 502 | Unreachable |
| 503 | Server overloaded (OLLAMA_MAX_QUEUE exceeded) |

Error format: `{"error": "description"}`

**Environment variables:**
- `OLLAMA_KEEP_ALIVE` — model persistence (default 5m)
- `OLLAMA_NUM_PARALLEL` — concurrent requests per model
- `OLLAMA_MAX_QUEUE` — queue depth before 503

## 4. Design Decisions (Pending)

These need to be resolved during Phase 8 planning:

### D-14: LLM Client Architecture
- **Option A:** Single `LLMClient` class with strategy pattern for each provider
- **Option B:** Three separate client functions, orchestrated by a `fallback_chain()`
- **Recommendation:** Option B — simpler, YAGNI, each client is ~30 lines

### D-15: Scoring Prompt Design
- 5 criteria: Kelly criterion relevance, mathematical rigor, novelty, practical applicability, data quality
- Each scored 0-1, aggregate = weighted average or simple mean
- JSON output format: `{"scores": {"kelly": 0.8, ...}, "overall": 0.72, "reasoning": "..."}`

### D-16: Prompt Versioning
- Store prompt template version (e.g., `v1`) in config or DB
- Score reproducibility: same prompt version + same model = comparable scores
- Simple approach: version string in `analyzer_config.json`

### D-17: Threshold Strategy
- Default threshold: 0.6
- Configurable via `analyzer_config.json`
- Papers >= threshold → `stage='analyzed'`
- Papers < threshold → `stage='rejected'`
