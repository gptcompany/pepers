# Summary: Plan 24-01 — Skill Alignment + GET Endpoints

## Retroactive Documentation

This phase was executed in a previous session (2026-02-15) and is being documented retroactively for GSD tracking continuity.

## What Was Done

### 1. GET /papers and GET /formulas Endpoints
- Added to `services/orchestrator/main.py`
- `GET /papers?stage=analyzed&limit=50` — list papers with filters
- `GET /papers?id=42` — single paper with nested formulas, validations, generated code
- `GET /formulas?paper_id=1&stage=validated&limit=50` — list formulas with filters
- Helper methods: `_query_params()`, `_list_papers()`, `_get_paper_detail()`

### 2. Skill Updates
- `/research` skill (`~/.claude/commands/research.md`): Replaced direct API calls with pipeline delegation via `localhost:8775`
- `/research-papers` skill (`~/.claude/commands/research-papers.md`): Complete rewrite from PostgreSQL/RAG to HTTP pipeline endpoints

### 3. E2E Re-test
- All 6 services healthy (ports 8770-8775)
- Pipeline run completed (2 stages, 17738ms)
- All new endpoints verified against live Docker pipeline
- smoke_results.json updated: 0 bugs, production_ready: true

### 4. Integration Tests
- 11 new tests in `tests/integration/test_orchestrator_db.py`
- `TestQueryEndpoints` class covering all GET endpoint scenarios
- Total: 25 integration tests passing, 105 unit tests passing

## Files Modified

| File | Changes |
|------|---------|
| `services/orchestrator/main.py` | +GET /papers, +GET /formulas, +helpers (~80 LOC) |
| `tests/integration/test_orchestrator_db.py` | +11 integration tests (~130 LOC) |
| `tests/smoke/smoke_results.json` | Updated with Phase 24 results |
| `~/.claude/commands/research.md` | Skill aligned to pipeline |
| `~/.claude/commands/research-papers.md` | Complete rewrite |

## Stats

- **LOC added**: ~210 (80 production + 130 tests)
- **Tests**: 11 new, all passing
- **Bugs found**: 0
- **Duration**: 1 session

## Git Commits

- `ec9f830` — GET endpoints + integration tests (research-pipeline)
- `8b86735` — Skill alignment (claude-config)
