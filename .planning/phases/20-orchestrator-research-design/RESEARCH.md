# Research: Phase 20 — Orchestrator + Docker

## Codebase Architecture Summary

### Service Inventory

| Service | Port | Entry Point | /process Contract |
|---------|------|-------------|-------------------|
| Discovery | 8770 | `python -m services.discovery.main` | `{query, max_results}` → papers found/enriched |
| Analyzer | 8771 | `python -m services.analyzer.main` | `{paper_id?, max_papers?}` → papers scored/rejected |
| Extractor | 8772 | `python -m services.extractor.main` | `{paper_id?, max_papers?}` → formulas extracted |
| Validator | 8773 | `python -m services.validator.main` | `{paper_id?, formula_id?, max_formulas?}` → CAS validation |
| Codegen | 8774 | `python -m services.codegen.main` | `{paper_id?, formula_id?, max_formulas?}` → code generated |
| **Orchestrator** | **8775** | TBD | TBD |

### Pipeline Stage Flow

```
discovered → analyzed → (rejected) → extracted → validated → codegen → complete
                                                                         ↑ (or failed at any point)
```

### Shared Infrastructure

- **DB**: SQLite WAL mode, `data/research.db`, 5 tables (papers, formulas, validations, generated_code, schema_version)
- **Config**: `RP_*` env vars, `shared/config.py` with per-service port mapping
- **HTTP**: stdlib `BaseHTTPRequestHandler` + `@route` decorator, JSON structured logging
- **Models**: 9 Pydantic v2 models, `PipelineStage` enum tracks progress
- **LLM**: `shared/llm.py` with fallback chain (Gemini CLI → Gemini SDK → Ollama)

### External Dependencies

| Service | External | Purpose |
|---------|----------|---------|
| Discovery | arXiv, Semantic Scholar, CrossRef | Paper search + enrichment |
| Extractor | arXiv export, RAGAnything (8767) | PDF download + text extraction |
| Validator | CAS service (8769) | Formula validation |
| Analyzer/Codegen | Ollama (11434), Gemini API | LLM scoring/explanation |

## Docker Architecture Decisions

### SQLite + Docker: Key Constraint

SQLite is file-based, not client-server. Multiple containers sharing the same `.db` file works **only if**:
1. All containers share the same Linux kernel (Linux host, not Docker Desktop)
2. Named Docker volume (not NFS/network FS)
3. WAL mode + `busy_timeout` + same UID across containers

**For this pipeline**: write contention is minimal because the orchestrator calls services **sequentially** (one at a time). Only one service writes at a time. No need for a DB gateway pattern.

### Decision: Shared Volume (No Gateway)

- All containers mount `sqlite-data:/data`
- WAL mode already configured in `shared/db.py`
- `busy_timeout=5000` already set
- Sequential processing = no concurrent writer conflicts
- Simpler architecture, fewer moving parts

### Base Image: python:3.12-slim

- `python:3.12-slim` (~41MB compressed) over Alpine (~17MB)
- Alpine uses musl libc — risk of segfaults with C extensions
- SymPy is pure Python (works on both), but slim avoids future issues
- Multi-stage build for minimal image size

### Cron Scheduling: APScheduler in Orchestrator

- **NOT** host cron (tight coupling, must know container names)
- **NOT** traditional cron in container (broken env vars, zombie processes)
- **APScheduler `BlockingScheduler`** inside orchestrator container:
  - Full access to env vars and Python config
  - Travels with Docker Compose stack
  - Pure Python, no extra binary

### Health Checks: Python stdlib

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:PORT/health')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

- Uses existing `/health` endpoints (already in BaseHandler)
- No `curl`/`wget` dependency in slim images
- `depends_on` with `condition: service_healthy` for startup ordering

### Dependency Ordering

```yaml
depends_on:
  service-name:
    condition: service_healthy
    restart: true  # Auto-restart if dependency restarts
```

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SQLite sharing | Shared volume | Sequential pipeline, minimal write contention |
| Base image | python:3.12-slim | Compatibility, ecosystem support |
| Cron | APScheduler in orchestrator | Pure Python, no host coupling |
| Health checks | Python urllib → /health | Already implemented, no extra deps |
| Startup order | depends_on + service_healthy | Compose v2 native |
| Container UID | Same user across all | Required for WAL SHM file access |

## Scope Change: Docker vs systemd

**Original (PROJECT.md)**: "Docker containerization — systemd native services, no Docker overhead" was Out of Scope.

**New decision**: User chose Docker deployment during v7.0 milestone discussion. PROJECT.md needs updating to reflect this change.

## Orchestrator Design Direction

The orchestrator should:
1. **HTTP endpoint** (`POST /run`): accepts keywords, triggers full pipeline
2. **Cron scheduler**: APScheduler with configurable schedule (default: daily 8AM)
3. **Sequential dispatch**: calls each service's `/process` in order
4. **Error handling**: per-stage retry, stage-level failure doesn't block previous stages
5. **Status tracking**: records pipeline run results in DB or file
6. **Health endpoint**: reports own status + all downstream service health
