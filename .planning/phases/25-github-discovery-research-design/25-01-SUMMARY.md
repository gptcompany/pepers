# Plan 25-01 Summary: GitHub Discovery Research & Design

## Status: COMPLETE

## Deliverables

| File | Action | Description |
|------|--------|-------------|
| DESIGN.md | Created | Full architecture document for Phase 26 implementation |
| CONTEXT.md | Created | Research findings + user decisions |
| PROJECT.md | Updated | Added GitHub Discovery to Active requirements |
| ROADMAP.md | Updated | Phase 25 marked complete |
| STATE.md | Updated | Current position → Phase 26 |

## DESIGN.md Contents

1. **Architecture**: 6-step data flow (paper context → search → clone → analyze → store → return)
2. **SQLite Schema**: 2 new tables (`github_repos`, `github_analyses`) with FK to papers + 4 indexes
3. **Pydantic Models**: `GitHubRepo`, `GitHubAnalysis` with JSON field validators
4. **API Contract**: `POST /search-github` (trigger) + `GET /github-repos` (query)
5. **GitHub Search Strategy**: Multi-language queries, PAT auth, rate limiting, keyword extraction
6. **Gemini CLI Integration**: CLI flags (verified), SDK fallback, rate limiting, dynamic prompt
7. **Configuration**: 9 new env vars with RP_GITHUB_ prefix
8. **Error Handling**: Per-error action table covering GitHub, Gemini, and clone failures
9. **Testing Strategy**: Unit, integration, E2E test plan for Phase 27

## Research Findings Applied

- Gemini CLI flags verified against official docs (deprecation warnings for `-p` and `--yolo`)
- GitHub API rate limits verified live (30 search req/min with PAT)
- Papers With Code shutdown (Jul 2025) confirmed — no alternative found
- Head-start module (297 LOC) validated: correct Gemini flags, good prompt structure, gaps identified

## Decisions Captured

| Decision | Choice |
|----------|--------|
| Analysis engine | Gemini CLI (host) + SDK fallback (Docker) |
| GitHub auth | PAT from SSOT (30 req/min) |
| Storage | New SQLite tables with FK to papers |
| Languages | Python + Rust + C++ |
| Model | gemini-2.5-pro (configurable) |

## Time

- Research: 3 parallel agents (Gemini CLI, GitHub API, prompt engineering) + 1 GitHub search
- Design: 1 plan, 7 tasks → DESIGN.md
- Gate: Context 98%, Plan 100% (auto-approved)
