# Phase 25: GitHub Discovery — Design Document

## Overview

Add GitHub repository search and Gemini-powered code analysis to the research pipeline. Given a paper (title, abstract, formulas), search GitHub for existing implementations, clone the most promising repos, and analyze them with Gemini CLI (1M context) to assess relevance, formula matches, and code quality.

**New module**: `services/orchestrator/github_search.py` (refine existing 297 LOC head-start)
**New endpoint**: `POST /search-github`, `GET /github-repos`
**New tables**: `github_repos`, `github_analyses`
**New models**: `GitHubRepo`, `GitHubAnalysis`, `SearchGitHubRequest`, `SearchGitHubResponse`

## Architecture

```
POST /search-github {paper_id: 42, max_repos: 3}
        │
        ▼
┌─────────────────────────────────────────┐
│ 1. Load paper context                    │
│    GET /papers?id=42 (internal)          │
│    → title, abstract, formulas           │
└────────────────┬────────────────────────┘
                 ▼
┌─────────────────────────────────────────┐
│ 2. Generate search queries               │
│    Per language: python, rust, cpp        │
│    "paper title" language:X stars:>N     │
│    + fallback: keywords in:readme        │
└────────────────┬────────────────────────┘
                 ▼
┌─────────────────────────────────────────┐
│ 3. GitHub Search API                     │
│    Authorization: Bearer $GITHUB_PAT     │
│    Rate: 30 req/min (search bucket)      │
│    → Merge + dedup by full_name          │
│    → Store in github_repos table         │
└────────────────┬────────────────────────┘
                 ▼
┌─────────────────────────────────────────┐
│ 4. Clone top N repos (shallow)           │
│    git clone --depth 1 → /tmp/           │
└────────────────┬────────────────────────┘
                 ▼
┌─────────────────────────────────────────┐
│ 5. Analyze with Gemini                   │
│    CLI: gemini "prompt"                  │
│      --include-directories /tmp/repo     │
│      -m gemini-2.5-pro                   │
│      --approval-mode yolo -o json        │
│    Fallback: SDK + concatenated files    │
│    → Store in github_analyses table      │
└────────────────┬────────────────────────┘
                 ▼
┌─────────────────────────────────────────┐
│ 6. Cleanup + Return results              │
│    rm -rf /tmp/research-github-*         │
│    → SearchGitHubResponse JSON           │
└─────────────────────────────────────────┘
```

## SQLite Schema Extension

Add to `shared/db.py` SCHEMA string (after `generated_code` table):

```sql
-- github_repos: discovered GitHub repositories (GitHub Discovery module)
CREATE TABLE IF NOT EXISTS github_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    full_name TEXT NOT NULL,
    url TEXT NOT NULL,
    clone_url TEXT NOT NULL,
    description TEXT,
    stars INTEGER DEFAULT 0,
    language TEXT,
    updated_at TEXT,
    topics TEXT,                    -- JSON array
    search_query TEXT,             -- query that found this repo
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(paper_id, full_name)   -- no duplicate repo per paper
);

-- github_analyses: Gemini analysis results per repo
CREATE TABLE IF NOT EXISTS github_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES github_repos(id),
    relevance_score INTEGER,       -- 0-100
    quality_score INTEGER,         -- 0-100
    formula_matches TEXT,          -- JSON array of match objects
    summary TEXT,
    recommendation TEXT,           -- USE, REFERENCE, SKIP
    key_files TEXT,                -- JSON array
    dependencies TEXT,             -- JSON array
    model_used TEXT,
    analysis_time_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Add to `shared/db.py` INDEXES string:

```sql
CREATE INDEX IF NOT EXISTS idx_github_repos_paper_id ON github_repos(paper_id);
CREATE INDEX IF NOT EXISTS idx_github_repos_full_name ON github_repos(full_name);
CREATE INDEX IF NOT EXISTS idx_github_analyses_repo_id ON github_analyses(repo_id);
CREATE INDEX IF NOT EXISTS idx_github_analyses_recommendation ON github_analyses(recommendation);
```

Schema version bump: `INSERT OR IGNORE INTO schema_version (version) VALUES (2)` with migration guard.

## Pydantic Models

Add to `shared/models.py`:

```python
class GitHubRepo(BaseModel):
    """Discovered GitHub repository for a paper."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    paper_id: int
    full_name: str
    url: str
    clone_url: str
    description: str | None = None
    stars: int = 0
    language: str | None = None
    updated_at: str | None = None
    topics: list[str] = []
    search_query: str | None = None
    created_at: datetime | None = None

    @field_validator("topics", mode="before")
    @classmethod
    def parse_topics(cls, v: object) -> list:
        return _parse_json_list(v)


class GitHubAnalysis(BaseModel):
    """Gemini analysis result for a GitHub repository."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    repo_id: int
    relevance_score: int | None = None
    quality_score: int | None = None
    formula_matches: list[dict] = []
    summary: str | None = None
    recommendation: str | None = None      # USE, REFERENCE, SKIP
    key_files: list[str] = []
    dependencies: list[str] = []
    model_used: str | None = None
    analysis_time_ms: int | None = None
    error: str | None = None
    created_at: datetime | None = None

    @field_validator("formula_matches", "key_files", "dependencies", mode="before")
    @classmethod
    def parse_json_lists(cls, v: object) -> list:
        return _parse_json_list(v)
```

## API Contract

### POST /search-github

**Request:**
```json
{
    "paper_id": 42,
    "max_repos": 3,
    "languages": ["python", "rust", "cpp"],
    "min_stars": 5,
    "query_override": null,
    "force": false
}
```

All fields except `paper_id` are optional with defaults shown.

**Response (200):**
```json
{
    "paper_id": 42,
    "repos_found": 15,
    "repos_analyzed": 3,
    "results": [
        {
            "repo": {
                "id": 1,
                "paper_id": 42,
                "full_name": "deltaray-io/kelly-criterion",
                "url": "https://github.com/deltaray-io/kelly-criterion",
                "stars": 108,
                "language": "Python"
            },
            "analysis": {
                "id": 1,
                "repo_id": 1,
                "relevance_score": 85,
                "quality_score": 72,
                "formula_matches": [
                    {
                        "formula_latex": "f^* = \\frac{p(b+1) - 1}{b}",
                        "code_file": "kelly/calculator.py",
                        "function_name": "optimal_fraction",
                        "match_quality": "exact"
                    }
                ],
                "summary": "Well-maintained Kelly criterion calculator with exact formula implementation.",
                "recommendation": "USE",
                "key_files": ["kelly/calculator.py", "kelly/portfolio.py"],
                "dependencies": ["numpy", "scipy"],
                "model_used": "gemini-2.5-pro"
            }
        }
    ],
    "errors": []
}
```

**Error responses:**
- `400 VALIDATION_ERROR`: Missing paper_id or invalid params
- `404 NOT_FOUND`: Paper not found
- `429 RATE_LIMITED`: GitHub or Gemini rate limit hit
- `500 INTERNAL_ERROR`: Unexpected error

### GET /github-repos

**Query parameters:**
- `paper_id` (required): Filter by paper
- `recommendation`: Filter by USE/REFERENCE/SKIP
- `limit`: Max results (default 50, max 200)

**Response (200):**
```json
[
    {
        "repo": { ... },
        "analysis": { ... }
    }
]
```

## GitHub Search Strategy

### Query Generation

Given a paper with title "Optimal Kelly Criterion Strategies for Growth-Rate Maximization":

**Primary queries** (one per language):
```
q="Optimal Kelly Criterion" language:python stars:>5 pushed:>2024-01-01 archived:false
q="Optimal Kelly Criterion" language:rust stars:>5 pushed:>2024-01-01 archived:false
q="Optimal Kelly Criterion" language:cpp stars:>5 pushed:>2024-01-01 archived:false
```

**Fallback queries** (if primary returns <3 results):
```
q=kelly criterion portfolio optimization in:readme language:python stars:>2
```

**Keyword extraction** from title/abstract:
1. Remove stop words and common academic words ("optimal", "analysis", "study")
2. Keep domain-specific terms ("Kelly", "criterion", "growth-rate", "maximization")
3. Limit to 4-5 keywords

### Authentication

```python
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ.get('GITHUB_PAT', '')}",
    "X-GitHub-Api-Version": "2022-11-28",
}
```

### Rate Limiting

```python
# Track from response headers
remaining = int(resp.headers.get("x-ratelimit-remaining", "30"))
reset_at = int(resp.headers.get("x-ratelimit-reset", "0"))

if remaining < 2:
    sleep_until = reset_at - time.time()
    if sleep_until > 0:
        time.sleep(sleep_until + 1)
```

### Multi-Language Merge

```python
all_repos = {}
for lang in languages:
    repos = search_github(query, language=lang, ...)
    for repo in repos:
        if repo["full_name"] not in all_repos:
            all_repos[repo["full_name"]] = repo

# Sort by stars, take top max_repos
sorted_repos = sorted(all_repos.values(), key=lambda r: r["stars"], reverse=True)
```

## Gemini CLI Integration

### CLI Invocation (Host)

```python
result = subprocess.run(
    [
        "gemini", prompt_text,
        "--include-directories", str(clone_path),
        "-m", model,
        "--approval-mode", "yolo",
        "-o", "json",
        "-e", "none",
    ],
    capture_output=True,
    text=True,
    timeout=timeout,
    stdin=subprocess.DEVNULL,
)

# Parse JSON output
data = json.loads(result.stdout)
response = data.get("response", "")
analysis = _parse_json_response(response)
```

**Note**: Use positional argument for prompt (not `-p` which is deprecated). Use `--approval-mode yolo` (not `--yolo` which is deprecated).

### SDK Fallback (Docker)

```python
from shared.llm import call_gemini_sdk

files_content = _read_repo_files(clone_path, max_chars=400_000)
full_prompt = f"{prompt}\n\n## Repository Source Code\n\n{files_content}"
response = call_gemini_sdk(full_prompt, system="", model=model)
```

SDK fallback reads Python/Rust/C++ files from the repo and concatenates them into the prompt. Max 400K chars (~100K tokens) to stay within context window.

### File Reading (Extended for Multi-Language)

```python
EXTENSIONS = {"*.py", "*.rs", "*.cpp", "*.hpp", "*.c", "*.h"}
SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git", "target", "build"}
```

### Rate Limiting Between Analyses

```python
gemini_rpm = int(os.environ.get("RP_GITHUB_GEMINI_RPM", "5"))
sleep_between = 60.0 / gemini_rpm  # 12 seconds for free tier
time.sleep(sleep_between)
```

### Dynamic Prompt (Refinement)

The existing `build_dynamic_prompt()` is good. Changes for Phase 26:
1. Add multi-language awareness to analysis tasks
2. Add formula variable mapping (not just file/function)
3. Request structured JSON with explicit schema validation hint

## Configuration

New environment variables (all optional with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_GITHUB_PAT` | `$GITHUB_PAT` | GitHub Personal Access Token |
| `RP_GITHUB_MAX_REPOS` | `3` | Default max repos to analyze per paper |
| `RP_GITHUB_MIN_STARS` | `5` | Minimum stars filter |
| `RP_GITHUB_LANGUAGES` | `python,rust,cpp` | Languages to search |
| `RP_GITHUB_ANALYSIS_MODEL` | `gemini-2.5-pro` | Gemini model for analysis |
| `RP_GITHUB_GEMINI_RPM` | `5` | Gemini requests per minute (rate limit) |
| `RP_GITHUB_CLONE_TIMEOUT` | `60` | Git clone timeout (seconds) |
| `RP_GITHUB_ANALYSIS_TIMEOUT` | `180` | Gemini analysis timeout (seconds) |
| `RP_GITHUB_MAX_REPO_SIZE` | `500000` | Skip repos larger than this (KB) |

## Error Handling

| Error | Action |
|-------|--------|
| GitHub 403/429 (rate limit) | Sleep until `x-ratelimit-reset`, retry once |
| GitHub search returns 0 results | Return empty results, no error |
| Git clone fails (timeout/auth) | Skip repo, log warning, continue to next |
| Gemini CLI not found | Fall back to SDK |
| Gemini CLI timeout | Fall back to SDK |
| Gemini JSON parse error | Retry with fence stripping, then skip |
| SDK fallback also fails | Store error in github_analyses, continue |
| Paper not found | Return 404 |
| All repos fail analysis | Return results with per-repo errors |

## Testing Strategy (Phase 27)

### Unit Tests
- `test_search_github()` — mock GitHub API response
- `test_clone_repo()` — mock subprocess
- `test_build_dynamic_prompt()` — verify prompt structure with various paper contexts
- `test_analyze_with_gemini_cli()` — mock subprocess for CLI, verify JSON parsing
- `test_parse_json_response()` — various edge cases (fences, truncated, etc.)
- `test_rate_limiting()` — verify sleep behavior
- `test_multi_language_merge()` — dedup, sort by stars

### Integration Tests
- `test_post_search_github()` — full endpoint with mocked GitHub + Gemini
- `test_get_github_repos()` — query stored results
- `test_sqlite_schema()` — table creation, foreign keys, unique constraints
- `test_pydantic_models()` — serialization/deserialization round-trip

### E2E Tests
- `test_real_github_search()` — live GitHub API call (requires PAT)
- `test_real_gemini_analysis()` — live Gemini CLI call (requires CLI + auth)
- `test_full_flow()` — paper → search → clone → analyze → store → query
