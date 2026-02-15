# Phase 25: GitHub Discovery Research & Design — Context

## Phase Goal

Research Gemini CLI capabilities, GitHub REST API patterns, and prompt engineering for code analysis. Produce DESIGN.md for implementation in Phase 26.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Gemini analysis engine | CLI on host, SDK fallback in Docker | CLI has native `--include-directories` for 1M context; SDK fallback when CLI unavailable (Docker containers) |
| GitHub authentication | PAT from SSOT (`GITHUB_PAT`) | 30 req/min search (vs 10 unauth), 5000 core/h |
| Result storage | New SQLite tables (`github_repos`, `github_analyses`) | Foreign key to `papers`, queryable, persistent |
| Language scope | Python + Rust + C++ | Aligned with codegen service output languages |
| Gemini model | `gemini-2.5-pro` (configurable via `RP_GITHUB_ANALYSIS_MODEL`) | 1M context, best reasoning for code analysis |
| Rate limiting | Built-in sleep/backoff for both GitHub (30/min) and Gemini (5 RPM free, more with billing) | Prevent 429 errors in batch processing |

## Research Findings

### Gemini CLI (Verified)

- **Package**: `@google/gemini-cli` (npm), requires Node.js 18+
- **Headless mode**: `gemini -p "prompt" --include-directories ./repo -m gemini-2.5-pro --approval-mode yolo -o json`
- **JSON output**: `{"response": "...", "stats": {...}, "error": null}`
- **Free tier**: 5 RPM / 100 RPD for Gemini 2.5 Pro (cut 50-92% in Dec 2025)
- **Paid Tier 1**: 150-300 RPM (enable billing)
- **Known bugs**: `--include-directories` may not always work (#13669), JSON output issues (#9009)
- **Extensions**: `-e none` disables all extensions (important for headless automation)
- **Stdin**: `cat file | gemini -p "analyze"` supported
- **Deprecated flags**: `-p` → positional arg, `--yolo` → `--approval-mode yolo`

### GitHub Search API (Verified Live)

- **Endpoint**: `GET /search/repositories?q=...&sort=stars&per_page=100`
- **Search rate limit**: 30 req/min (PAT), 10 req/min (unauth) — separate from core API
- **Result cap**: Only first 1,000 results accessible
- **Key qualifiers**: `in:readme`, `in:description`, `language:python`, `stars:>N`, `pushed:>DATE`, `topic:X`, `archived:false`
- **Live test**: "kelly criterion language:python stars:>5" → 11 results, top: deltaray-io/kelly-criterion (108 stars)
- **Pagination**: `Link` header with `rel="next"`, `per_page` max 100

### Existing Projects (None Match Our Use Case)

- **Papers With Code**: Shut down by Meta July 2025 — static dataset frozen on GitHub
- **Repomix** (21.8k stars): Packs repos for LLM analysis — useful utility, not our pipeline
- **Gemini-CLI-Git-Ask**: REST API + MCP for repo analysis with Gemini — architecture reference
- **Paper2Code** (4k stars): Generates code FROM papers (not finding existing implementations)
- **PapersFlow**: Web service, not open source — does find implementations but no API
- **Conclusion**: No existing OSS tool does "paper → GitHub implementation search → LLM analysis"

### Head-Start Module Assessment

`services/orchestrator/github_search.py` (297 LOC) already implements:
- ✅ GitHub search via REST API (basic)
- ✅ Shallow clone + cleanup
- ✅ Dynamic prompt builder from paper context
- ✅ Gemini CLI invocation with correct flags
- ✅ SDK fallback with file content concatenation
- ✅ JSON response parsing with fence stripping
- ✅ Full flow: search → clone → analyze → cleanup

**Gaps to address in Phase 26:**
- ❌ No PAT authentication (currently unauthenticated)
- ❌ No rate limiting / backoff
- ❌ Hardcoded `language:python` (needs Python + Rust + C++)
- ❌ No `per_page=100` (uses 30)
- ❌ No SQLite storage of results
- ❌ No `/search-github` HTTP endpoint
- ❌ No Pydantic models for results
- ❌ No retry on clone failure
- ❌ Missing `pushed:>DATE` and `stars:>N` quality filters

## Constraints

- Gemini CLI runs on **host only** (not in Docker) — SDK fallback required for containerized deployment
- GitHub search rate: 30 req/min with PAT — batch of 10 papers × 3 repos each = 30 search requests (fits in 1 minute)
- Gemini free tier: 5 RPM — analyzing 30 repos takes ~6 minutes minimum (acceptable for daily batch)
- Repo clone: shallow (`--depth 1`) to /tmp, cleanup after analysis
- Max repo size: skip repos with `size:>500000` (500MB) to avoid disk/bandwidth issues

## Dependencies

- Phase 24 complete (GET /papers, GET /formulas endpoints available)
- `GITHUB_PAT` in SSOT `/media/sam/1TB/.env`
- `GEMINI_API_KEY` in SSOT (for SDK fallback)
- Gemini CLI installed on host (`npm install -g @google/gemini-cli`)
- git installed (for clone operations)
