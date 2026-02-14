# Context: Phase 21 — Orchestrator Implementation + Docker Deploy

**Gathered:** 2026-02-14
**Source:** Phase 20 DESIGN.md + codebase exploration

## Phase Goal

Implement the orchestrator service (port 8775) and Docker Compose deployment for all 6 services.

## What Exists

- 5 working services: Discovery (8770), Analyzer (8771), Extractor (8772), Validator (8773), Codegen (8774)
- Shared library: server.py (BaseHandler/BaseService), config.py, db.py, models.py, llm.py
- 432 total tests (403 non-e2e + 29 e2e), 86% coverage on codegen
- pyproject.toml with: pydantic, arxiv, requests, google-genai
- No Dockerfile, no docker-compose.yml, no .env at project root
- APScheduler 3.11.2 installed in venv but NOT in pyproject.toml
- SymPy 1.14.0 installed in venv but NOT in pyproject.toml

## What to Build

### 1. Orchestrator Service (~370 LOC across 3 files)

- `services/orchestrator/__init__.py` — package init
- `services/orchestrator/main.py` (~120 LOC) — OrchestratorHandler + main()
- `services/orchestrator/pipeline.py` (~200 LOC) — PipelineRunner, dispatch, retry
- `services/orchestrator/scheduler.py` (~50 LOC) — APScheduler cron setup

### 2. Docker Artifacts

- `Dockerfile` — multi-stage build (builder + runtime), ARG SERVICE selector
- `docker-compose.yml` — 6 services, network_mode:host, sqlite-data volume, health checks
- `.env` — dotenvx encrypted secrets for Docker (GEMINI_API_KEY minimum)

### 3. Dependency Updates

- Add `apscheduler>=3.10` to pyproject.toml dependencies
- Add `sympy>=1.12` to pyproject.toml dependencies (already used by codegen, never declared)

## Key Design Decisions (from Phase 20)

- Sequential stage dispatch (not parallel)
- Retry: 3 retries, backoff 4^attempt (1s, 4s, 16s), 300s timeout
- Cron: APScheduler BackgroundScheduler, default "0 8 * * *"
- Docker: network_mode:host, shared sqlite-data volume, user 1000:1000
- Error handling: per-paper isolation (services handle), service-level retry (orchestrator)
- API: POST /run, GET /status, GET /status/services, GET /health

## Patterns to Follow

- BaseHandler + @route decorator (shared/server.py)
- load_config("orchestrator") for env vars (shared/config.py)
- transaction() for DB access (shared/db.py)
- requests library for HTTP calls to services
- JSON structured logging

## Risks

- SQLite concurrent access with Docker volumes: mitigated by WAL mode + sequential writes
- APScheduler thread safety: BackgroundScheduler runs in background thread, HTTP server in main thread — safe with SQLite WAL
- GEMINI_API_KEY in .env: dotenvx encryption, .env.keys in .gitignore
