# Summary: Phase 20-01 — Orchestrator Research & Design

**Completed:** 2026-02-14
**Plan:** 20-01 (Design orchestrator architecture + Docker deployment)

## What Was Done

### Task 1: Extracted Service Contracts
- Read all 5 service handlers (`discovery`, `analyzer`, `extractor`, `validator`, `codegen`) and shared library (`config.py`, `server.py`, `db.py`, `models.py`)
- Documented exact `/process` request/response JSON for each service
- Mapped stage transitions: `discovered → analyzed/rejected → extracted → validated → codegen`
- Identified all external dependencies per service (arXiv, S2, CrossRef, RAGAnything, CAS, Ollama, Gemini)
- Confirmed port assignments (8770–8774) and orchestrator reserved at 8775
- Verified `BaseHandler` pattern: `/health` and `/status` auto-registered for all services

### Task 2: Created DESIGN.md (8 Sections)
Full architectural blueprint covering:
1. **Service Architecture**: port 8775, BaseHandler pattern, two modes (manual + cron)
2. **API Contract**: `POST /run`, `GET /status`, `GET /health`, `GET /status/services` with exact JSON schemas
3. **Orchestration Flow**: stage mapping table, parameter forwarding matrix, 3 sequence diagrams (manual, cron, error/retry)
4. **Error Handling**: per-paper isolation (services handle internally), service-level retry (3 attempts, exponential backoff 1s/4s/16s)
5. **Cron Scheduling**: APScheduler BackgroundScheduler, configurable via `RP_ORCHESTRATOR_CRON`
6. **Docker Compose Layout**: full `docker-compose.yml` with 6 services, `network_mode: host`, shared `sqlite-data` volume, health checks, startup ordering
7. **Configuration**: 12 environment variables documented with defaults
8. **File Layout**: 3 new files (`main.py`, `pipeline.py`, `scheduler.py`) + Dockerfile + docker-compose.yml

### Task 3: Updated PROJECT.md
- Changed "Docker containerization" from Out of Scope to **IN SCOPE** for v7.0
- Updated Active requirements: orchestrator HTTP+cron, Docker Compose deployment
- Changed process management from systemd to Docker Compose
- Updated current state to "v7.0 in progress"
- Added 3 new key decisions: APScheduler, network_mode: host, shared SQLite volume

## Files Modified
- `.planning/phases/20-orchestrator-research-design/DESIGN.md` — **Created** (comprehensive 8-section architecture document)
- `.planning/PROJECT.md` — **Updated** (Docker in-scope, requirements, constraints, decisions)

## Verification
- [x] DESIGN.md exists with all 8 sections
- [x] API contracts have exact request/response JSON schemas
- [x] Docker compose design addresses SQLite sharing (shared volume, same UID, WAL)
- [x] External service connectivity addressed (network_mode: host)
- [x] Cron scheduling design uses APScheduler BackgroundScheduler
- [x] Error handling defines retry count (3), backoff (1s/4s/16s), failure behavior
- [x] PROJECT.md updated to reflect Docker in-scope
- [x] No implementation code written (design only)

## Metrics
- DESIGN.md: ~450 lines, 8 sections, 3 sequence diagrams
- PROJECT.md: 7 edits (scope, requirements, constraints, decisions)
- Services analyzed: 5 handlers + 4 shared modules = 9 files read
