# Phase 10 Context: Analyzer Testing

## Phase Goal

Comprehensive test suite for the Analyzer service — unit tests with mocked LLM responses, integration tests with real SQLite + mock LLM, E2E tests with real Ollama calls.

## What's Being Tested

### services/analyzer/prompt.py (81 LOC)
- `PROMPT_VERSION = "v1"` constant
- `SCORING_SYSTEM_PROMPT` — 5-criteria scoring instructions
- `EXPECTED_SCORE_KEYS` — frozenset of required keys
- `format_scoring_prompt(title, abstract, authors, categories)` — builds user prompt

### services/analyzer/llm.py (209 LOC)
- `_get_gemini_api_key()` — env var validation
- `_strip_markdown_fences(text)` — regex cleanup
- `call_gemini_cli(prompt, system, model, timeout)` — subprocess
- `call_gemini_sdk(prompt, system, model, timeout)` — google-genai SDK
- `call_ollama(prompt, system, model, timeout, base_url)` — HTTP POST
- `fallback_chain(prompt, system)` — try in order, return (text, provider)

### services/analyzer/main.py (310 LOC)
- `migrate_db(db_path)` — idempotent ADD COLUMN prompt_version
- `AnalyzerHandler` class with threshold=0.7, max_papers_default=10
- `handle_process(data)` — full flow: query → prompt → LLM → parse → score → DB update
- `_query_papers()`, `_parse_llm_response()`, `_update_paper_score()`

## Existing Test Patterns (from Phase 7 Discovery)

### Unit (tests/unit/test_discovery.py — 668 LOC)
- Class per function/component
- `@patch()` for external calls
- Test success + error paths
- Edge cases: empty, 404, 429, malformed

### Integration (tests/integration/test_discovery_db.py — 448 LOC)
- Real SQLite via `initialized_db` fixture
- Real HTTP server via BaseService in thread
- Mock external APIs, real DB

### E2E (tests/e2e/test_discovery_e2e.py — 110 LOC)
- `@pytest.mark.e2e` marker
- Real API calls
- Skip if unavailable

### Shared Fixtures (conftest.py — 144 LOC)
- `memory_db`, `tmp_db_path`, `initialized_db`
- `clean_env`, `sample_paper_row`
- `sample_arxiv_result`, `sample_s2_response`, `sample_crossref_response`

## Key Decisions

- Follow Discovery testing patterns exactly
- Unit: mock all 3 LLM providers, test fallback chain logic
- Integration: real DB + mock LLM, test full /process endpoint
- E2E: real Ollama (localhost:11434), skip if unavailable
- New fixtures: sample LLM responses (valid JSON, invalid, edge cases)
- Threshold testing: verify 0.7 boundary (accepted vs rejected)
- Score clamping: verify out-of-range values get clamped

## Concerns

- Gemini CLI test: need to mock subprocess.run carefully (stdin=DEVNULL)
- Gemini SDK test: need to mock google.genai module
- Ollama E2E: depends on localhost:11434 running with qwen3:8b
- Migration test: verify idempotent ADD COLUMN
