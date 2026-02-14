# DESIGN: Orchestrator Service + Docker Deployment

**Phase 20 — v7.0 Orchestrator + Deploy**
**Created:** 2026-02-14

---

## 1. Orchestrator Service Architecture

The orchestrator is the 6th microservice in the research pipeline. It coordinates the 5 existing services (Discovery → Analyzer → Extractor → Validator → Codegen) via HTTP calls to their `/process` endpoints.

**Key properties:**
- Port: **8775** (follows convention: 8770–8774 for services)
- Follows existing `BaseHandler` + `BaseService` pattern from `shared/server.py`
- Two operational modes: **manual** (per-paper HTTP) and **automatic** (cron)
- Talks to services via `http://localhost:PORT/process`
- Entry point: `python -m services.orchestrator.main`

**Environment variables:**
```
RP_ORCHESTRATOR_PORT=8775
RP_DB_PATH=data/research.db
RP_LOG_LEVEL=INFO
```

---

## 2. API Contract

### `POST /run` — Trigger pipeline execution

Starts a pipeline run. Supports three modes:
1. **Full pipeline from query**: provide `query` to start from Discovery
2. **Advance specific paper**: provide `paper_id` to advance one paper to next stage(s)
3. **Batch advance**: no `query`/`paper_id` — advance all pending papers

**Request:**
```json
{
    "query": "abs:\"Kelly criterion\" AND cat:q-fin.*",
    "paper_id": 42,
    "stages": 5,
    "max_papers": 10,
    "max_formulas": 50,
    "force": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str?` | `null` | arXiv search query — triggers Discovery stage |
| `paper_id` | `int?` | `null` | Advance specific paper to next stage(s) |
| `stages` | `int` | `5` | How many stages to advance (1–5). 5 = full pipeline |
| `max_papers` | `int` | `10` | Max papers per batch in Analyzer/Extractor |
| `max_formulas` | `int` | `50` | Max formulas per batch in Validator/Codegen |
| `force` | `bool` | `false` | Reprocess already-processed items |

**Response (200):**
```json
{
    "run_id": "run-20260214-083000-abc123",
    "status": "completed",
    "stages_completed": 5,
    "stages_requested": 5,
    "results": {
        "discovery": {
            "papers_found": 12,
            "papers_new": 8,
            "time_ms": 15200
        },
        "analyzer": {
            "papers_analyzed": 8,
            "papers_accepted": 5,
            "papers_rejected": 3,
            "time_ms": 42000
        },
        "extractor": {
            "papers_processed": 5,
            "formulas_extracted": 23,
            "time_ms": 180000
        },
        "validator": {
            "formulas_processed": 23,
            "formulas_valid": 18,
            "formulas_invalid": 3,
            "time_ms": 45000
        },
        "codegen": {
            "formulas_processed": 18,
            "code_generated": {"c99": 15, "rust": 14, "python": 16},
            "time_ms": 12000
        }
    },
    "errors": [],
    "time_ms": 294200
}
```

**Error response (4xx/5xx):**
```json
{
    "error": "Discovery service unavailable",
    "code": "SERVICE_UNAVAILABLE",
    "details": {"service": "discovery", "status_code": 503}
}
```

**Mode resolution logic:**
1. If `query` provided → start from Discovery, then continue for `stages` stages
2. If `paper_id` provided → determine paper's current stage, advance `stages` stages
3. If neither → batch mode: advance all pending papers by `stages` stages (same as cron)

### `GET /status` — Pipeline overview

Returns aggregate pipeline state.

**Response (200):**
```json
{
    "papers_by_stage": {
        "discovered": 42,
        "analyzed": 38,
        "rejected": 12,
        "extracted": 25,
        "validated": 20,
        "codegen": 15,
        "complete": 10,
        "failed": 3
    },
    "formulas_by_stage": {
        "extracted": 150,
        "validated": 120,
        "codegen": 95,
        "failed": 8
    },
    "last_run": {
        "run_id": "run-20260214-083000-abc123",
        "started_at": "2026-02-14T08:30:00",
        "status": "completed",
        "stages_completed": 5,
        "time_ms": 294200
    },
    "recent_errors": [
        {
            "paper_id": 15,
            "stage": "extractor",
            "error": "RAGAnything timeout after 120s",
            "timestamp": "2026-02-14T08:32:15"
        }
    ],
    "cron": {
        "enabled": true,
        "schedule": "0 8 * * *",
        "next_run": "2026-02-15T08:00:00",
        "last_run": "2026-02-14T08:00:00"
    }
}
```

### `GET /health` — Service health (inherited from BaseHandler)

Standard health check. Same format as all services.

**Response (200):**
```json
{
    "status": "ok",
    "service": "orchestrator",
    "uptime_seconds": 3600.5
}
```

### `GET /status/services` — Downstream service health

Calls each service's `/health` endpoint and returns aggregated status.

**Response (200):**
```json
{
    "all_healthy": true,
    "services": {
        "discovery":  {"status": "ok", "port": 8770, "uptime_seconds": 7200.1},
        "analyzer":   {"status": "ok", "port": 8771, "uptime_seconds": 7199.3},
        "extractor":  {"status": "ok", "port": 8772, "uptime_seconds": 7198.8},
        "validator":  {"status": "ok", "port": 8773, "uptime_seconds": 7197.2},
        "codegen":    {"status": "ok", "port": 8774, "uptime_seconds": 7196.5}
    }
}
```

If a service is unreachable:
```json
{
    "all_healthy": false,
    "services": {
        "discovery": {"status": "ok", "port": 8770, "uptime_seconds": 7200.1},
        "extractor": {"status": "error", "port": 8772, "error": "Connection refused"}
    }
}
```

---

## 3. Orchestration Flow

### Stage Mapping

Each service reads papers/formulas at a specific stage and advances them:

| Service | Reads Stage | Writes Stage | Operates On | Key Params |
|---------|-------------|--------------|-------------|------------|
| Discovery | *(none — creates new)* | `discovered` | papers | `query`, `max_results` |
| Analyzer | `discovered` | `analyzed` / `rejected` | papers | `paper_id`, `max_papers`, `force` |
| Extractor | `analyzed` | `extracted` | papers → formulas | `paper_id`, `max_papers`, `force` |
| Validator | `extracted` (formulas) | `validated` | formulas | `paper_id`, `formula_id`, `max_formulas`, `force` |
| Codegen | `validated` (formulas) | `codegen` | formulas | `paper_id`, `formula_id`, `max_formulas`, `force` |

### Dispatch Logic

The orchestrator calls services **sequentially** (one at a time). Within each stage, the service handles its own batching.

```python
STAGE_ORDER = [
    ("discovery", 8770),
    ("analyzer", 8771),
    ("extractor", 8772),
    ("validator", 8773),
    ("codegen", 8774),
]

def dispatch_stage(stage_name, port, params):
    """Call a service's /process endpoint."""
    url = f"http://localhost:{port}/process"
    resp = requests.post(url, json=params, timeout=300)
    resp.raise_for_status()
    return resp.json()
```

### Parameter Forwarding

The orchestrator forwards batch parameters to each downstream service:

| Orchestrator Param | Discovery | Analyzer | Extractor | Validator | Codegen |
|--------------------|-----------|----------|-----------|-----------|---------|
| `query` | `query` | — | — | — | — |
| `paper_id` | — | `paper_id` | `paper_id` | `paper_id` | `paper_id` |
| `max_papers` | `max_results` | `max_papers` | `max_papers` | — | — |
| `max_formulas` | — | — | — | `max_formulas` | `max_formulas` |
| `force` | — | `force` | `force` | `force` | `force` |

### Sequence Diagram: Manual Trigger (POST /run with paper_id)

```
User                Orchestrator        Analyzer         Extractor        Validator        Codegen
  |                      |                  |                |                |               |
  |-- POST /run -------->|                  |                |                |               |
  |   {paper_id:42,      |                  |                |                |               |
  |    stages:3}         |                  |                |                |               |
  |                      |                  |                |                |               |
  |                      |-- Query DB: paper 42 stage? ----->|                |               |
  |                      |<- stage="discovered" -------------|                |               |
  |                      |                  |                |                |               |
  |                      |-- POST /process->|                |                |               |
  |                      |   {paper_id:42}  |                |                |               |
  |                      |<- {analyzed,     |                |                |               |
  |                      |    score:0.85}   |                |                |               |
  |                      |                  |                |                |               |
  |                      |-- POST /process----------------->|                |               |
  |                      |   {paper_id:42}  |               |                |               |
  |                      |<- {extracted,    |               |                |               |
  |                      |    formulas:5}   |               |                |               |
  |                      |                  |                |                |               |
  |                      |-- POST /process--------------------------------->|               |
  |                      |   {paper_id:42}  |               |               |               |
  |                      |<- {validated,    |               |               |               |
  |                      |    valid:4}      |               |               |               |
  |                      |                  |                |                |               |
  |<- 200 {run_id,       |                  |                |                |               |
  |   stages_completed:3,|                  |                |                |               |
  |   results:{...}}     |                  |                |                |               |
```

### Sequence Diagram: Cron Batch Flow

```
APScheduler          Orchestrator        Discovery       Analyzer        Extractor
    |                     |                  |               |               |
    |-- trigger --------->|                  |               |               |
    |                     |                  |               |               |
    |                     |-- POST /process->|               |               |
    |                     |   {query:"...",  |               |               |
    |                     |    max_results:50}               |               |
    |                     |<- {found:12,     |               |               |
    |                     |    new:8}        |               |               |
    |                     |                  |               |               |
    |                     |-- POST /process--------------->|               |
    |                     |   {max_papers:10}|              |               |
    |                     |<- {analyzed:8,   |              |               |
    |                     |    accepted:5}   |              |               |
    |                     |                  |               |               |
    |                     |-- POST /process------------------------------>|
    |                     |   {max_papers:10}|              |              |
    |                     |<- {processed:5,  |              |              |
    |                     |    formulas:23}  |              |              |
    |                     |                  |               |               |
    |                     |   ... continues to Validator, Codegen ...      |
    |                     |                  |               |               |
    |<- run complete      |                  |               |               |
```

### Sequence Diagram: Error/Retry Flow

```
Orchestrator          Extractor           (retry logic)
    |                     |                    |
    |-- POST /process --->|                    |
    |<- 503 Service       |                    |
    |   Unavailable       |                    |
    |                     |                    |
    |-- wait 1s -------------------------------->|
    |                     |                    |
    |-- POST /process --->|                    |
    |<- 503 Service       |                    |
    |   Unavailable       |                    |
    |                     |                    |
    |-- wait 4s -------------------------------->|
    |                     |                    |
    |-- POST /process --->|                    |
    |<- 200 {processed:5} |                    |
    |                     |                    |
    |-- continue to       |                    |
    |   next stage        |                    |
```

If all retries fail:
```
    |-- POST /process --->|
    |<- 503               |
    |                     |
    |-- wait 16s ---------------------------->|
    |                     |
    |-- POST /process --->|
    |<- 503               |
    |                     |
    |-- STAGE FAILED:     |
    |   log error,        |
    |   record in results,|
    |   continue to       |
    |   next stage        |
```

---

## 4. Error Handling & Retry

### Per-Paper Error Isolation

One paper failing does NOT block the batch. Each service already implements per-paper error isolation:
- Discovery: skips papers that fail upsert/enrichment
- Analyzer: skips papers with invalid LLM responses
- Extractor: marks failed papers as `stage='failed'`, continues batch
- Validator: marks failed formulas as `stage='failed'`, continues batch
- Codegen: marks failed formulas as `stage='failed'`, continues batch

The orchestrator trusts each service's internal error handling and tracks aggregate results.

### Service-Level Retry (Orchestrator)

When a service `/process` call fails at the HTTP level (connection refused, 5xx, timeout):

| Parameter | Value | Env Var |
|-----------|-------|---------|
| Max retries | 3 | `RP_ORCHESTRATOR_RETRY_MAX` |
| Backoff base | 4.0 seconds | `RP_ORCHESTRATOR_RETRY_BACKOFF` |
| Backoff formula | `base^attempt` → 1s, 4s, 16s | — |
| Request timeout | 300s (5 min) | `RP_ORCHESTRATOR_TIMEOUT` |

```python
def call_service_with_retry(url, params, max_retries=3, backoff=4.0):
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=params, timeout=300)
            if resp.status_code < 500:
                return resp
            # 5xx: retry
        except (requests.ConnectionError, requests.Timeout):
            pass  # retry

        if attempt < max_retries:
            delay = backoff ** attempt  # 1, 4, 16
            time.sleep(delay)

    raise ServiceUnavailableError(f"{url} failed after {max_retries} retries")
```

### Retry Scope

- **Retry**: HTTP-level failures (connection refused, 5xx, timeout)
- **No retry**: Client errors (4xx) — these indicate bad input, not transient issues
- **Gemini 503/429**: Handled internally by services via `shared/llm.py` fallback chain. The orchestrator retries at the HTTP level if the service itself returns 5xx.

### Failure Behavior

After max retries exhausted for a stage:
1. Log the error with stage name and attempt count
2. Record the failure in the run results
3. **Continue to next stage** — other papers at the right stage may still be processable
4. Mark the run status as `"partial"` (not `"completed"`)

---

## 5. Cron Scheduling

### APScheduler in Orchestrator Process

The orchestrator runs APScheduler's `BackgroundScheduler` alongside the HTTP server in the same process.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

def create_scheduler(cron_expr, run_func):
    scheduler = BackgroundScheduler()
    trigger = CronTrigger.from_crontab(cron_expr)
    scheduler.add_job(run_func, trigger, id="pipeline_cron")
    return scheduler
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_ORCHESTRATOR_CRON` | `0 8 * * *` | Cron expression (daily at 08:00) |
| `RP_ORCHESTRATOR_CRON_ENABLED` | `true` | Enable/disable cron scheduler |
| `RP_ORCHESTRATOR_STAGES_PER_RUN` | `5` | Stages to advance per cron run (1–5) |
| `RP_ORCHESTRATOR_DEFAULT_QUERY` | `abs:"Kelly criterion" AND cat:q-fin.*` | Default Discovery query for cron |
| `RP_ORCHESTRATOR_CRON_MAX_PAPERS` | `10` | Max papers per cron batch |
| `RP_ORCHESTRATOR_CRON_MAX_FORMULAS` | `50` | Max formulas per cron batch |

### Cron Behavior

Each cron trigger is equivalent to:
```
POST /run {
    "query": "$RP_ORCHESTRATOR_DEFAULT_QUERY",
    "stages": $RP_ORCHESTRATOR_STAGES_PER_RUN,
    "max_papers": $RP_ORCHESTRATOR_CRON_MAX_PAPERS,
    "max_formulas": $RP_ORCHESTRATOR_CRON_MAX_FORMULAS
}
```

### Lifecycle

1. `main()` starts → `init_db()` → create scheduler → start scheduler → start HTTP server
2. Scheduler runs in background thread, triggers `cron_run()` on schedule
3. `cron_run()` calls the same pipeline logic as `POST /run`
4. HTTP server handles manual requests concurrently (via separate threads)
5. SIGTERM → stop scheduler → stop HTTP server

---

## 6. Docker Compose Layout

### Architecture Decision: `network_mode: host`

All containers use `network_mode: host` because:
- External services (RAGAnything:8767, CAS:8769, Ollama:11434) run on the host
- Services communicate via `localhost:PORT` — same as bare-metal
- Simplest networking, zero port mapping confusion
- No NAT overhead

**Trade-off**: No network isolation between containers. Acceptable for a single-machine deployment.

### docker-compose.yml

```yaml
name: research-pipeline

services:
  discovery:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: discovery
    network_mode: host
    environment:
      - RP_DISCOVERY_PORT=8770
      - RP_DB_PATH=/data/research.db
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8770/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  analyzer:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: analyzer
    network_mode: host
    environment:
      - RP_ANALYZER_PORT=8771
      - RP_DB_PATH=/data/research.db
      - RP_ANALYZER_THRESHOLD=0.7
      - RP_ANALYZER_MAX_PAPERS=10
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8771/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    depends_on:
      discovery:
        condition: service_healthy
        restart: true

  extractor:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: extractor
    network_mode: host
    environment:
      - RP_EXTRACTOR_PORT=8772
      - RP_DB_PATH=/data/research.db
      - RP_EXTRACTOR_MAX_PAPERS=10
      - RP_EXTRACTOR_PDF_DIR=/data/pdfs
      - RP_EXTRACTOR_RAG_URL=http://localhost:8767
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8772/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    depends_on:
      analyzer:
        condition: service_healthy
        restart: true

  validator:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: validator
    network_mode: host
    environment:
      - RP_VALIDATOR_PORT=8773
      - RP_DB_PATH=/data/research.db
      - RP_VALIDATOR_CAS_URL=http://localhost:8769
      - RP_VALIDATOR_MAX_FORMULAS=50
      - RP_VALIDATOR_ENGINES=sympy,maxima
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8773/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    depends_on:
      extractor:
        condition: service_healthy
        restart: true

  codegen:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: codegen
    network_mode: host
    environment:
      - RP_CODEGEN_PORT=8774
      - RP_DB_PATH=/data/research.db
      - RP_CODEGEN_OLLAMA_URL=http://localhost:11434
      - RP_CODEGEN_MAX_FORMULAS=50
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8774/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    depends_on:
      validator:
        condition: service_healthy
        restart: true

  orchestrator:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        SERVICE: orchestrator
    network_mode: host
    environment:
      - RP_ORCHESTRATOR_PORT=8775
      - RP_DB_PATH=/data/research.db
      - RP_ORCHESTRATOR_CRON=0 8 * * *
      - RP_ORCHESTRATOR_CRON_ENABLED=true
      - RP_ORCHESTRATOR_STAGES_PER_RUN=5
      - RP_ORCHESTRATOR_DEFAULT_QUERY=abs:"Kelly criterion" AND cat:q-fin.*
      - RP_ORCHESTRATOR_RETRY_MAX=3
      - RP_ORCHESTRATOR_RETRY_BACKOFF=4.0
      - RP_ORCHESTRATOR_TIMEOUT=300
      - RP_LOG_LEVEL=INFO
    env_file: .env
    volumes:
      - sqlite-data:/data
    user: "1000:1000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:8775/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    depends_on:
      codegen:
        condition: service_healthy
        restart: true

volumes:
  sqlite-data:
    driver: local
```

### SQLite Sharing Strategy

All 6 containers share a single named volume `sqlite-data` mounted at `/data`:
- **WAL mode**: Already configured in `shared/db.py` (`PRAGMA journal_mode=WAL`)
- **busy_timeout**: Not yet set (to be added in Phase 21: `PRAGMA busy_timeout=5000`)
- **Same UID**: All containers run as `user: "1000:1000"` — required for WAL SHM file access
- **Sequential writes**: Orchestrator calls services one-at-a-time, so concurrent writer conflicts are impossible
- **Named volume**: Linux native filesystem, not NFS — WAL locking works correctly

### Dockerfile (Multi-Stage Build)

```dockerfile
# Stage 1: Builder — install dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps (if any service needs them)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy source code
COPY shared/ shared/
COPY services/ services/

# Create data directory
RUN mkdir -p /data/pdfs

# Service selector via build arg
ARG SERVICE=orchestrator
ENV SERVICE_NAME=${SERVICE}

# Entry point
CMD ["sh", "-c", "python -m services.${SERVICE_NAME}.main"]
```

### External Service Connectivity

With `network_mode: host`, all external services are reachable at `localhost`:

| External Service | Address | Used By |
|------------------|---------|---------|
| RAGAnything | `http://localhost:8767` | Extractor |
| CAS Microservice | `http://localhost:8769` | Validator |
| Ollama | `http://localhost:11434` | Analyzer, Codegen |
| arXiv API | `https://export.arxiv.org` | Discovery, Extractor |
| Semantic Scholar | `https://api.semanticscholar.org` | Discovery |
| CrossRef | `https://api.crossref.org` | Discovery |
| Gemini API | `https://generativelanguage.googleapis.com` | Analyzer (fallback) |

---

## 7. Configuration

### All Orchestrator Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_ORCHESTRATOR_PORT` | `8775` | HTTP server port |
| `RP_ORCHESTRATOR_CRON` | `0 8 * * *` | Cron schedule (crontab syntax) |
| `RP_ORCHESTRATOR_CRON_ENABLED` | `true` | Enable/disable cron |
| `RP_ORCHESTRATOR_STAGES_PER_RUN` | `5` | Stages per cron run (1–5) |
| `RP_ORCHESTRATOR_DEFAULT_QUERY` | `abs:"Kelly criterion" AND cat:q-fin.*` | Default Discovery query |
| `RP_ORCHESTRATOR_CRON_MAX_PAPERS` | `10` | Max papers per cron batch |
| `RP_ORCHESTRATOR_CRON_MAX_FORMULAS` | `50` | Max formulas per cron batch |
| `RP_ORCHESTRATOR_RETRY_MAX` | `3` | Max retries per service call |
| `RP_ORCHESTRATOR_RETRY_BACKOFF` | `4.0` | Backoff base (seconds) |
| `RP_ORCHESTRATOR_TIMEOUT` | `300` | Request timeout (seconds) |
| `RP_DB_PATH` | `data/research.db` | SQLite database path |
| `RP_LOG_LEVEL` | `INFO` | Log level |

### Existing Service Variables (Referenced)

Each service already reads its own `RP_{SERVICE}_*` variables. The Docker compose sets these via `environment:` in each service definition. API keys (GEMINI_API_KEY) are loaded via `env_file: .env` (dotenvx encrypted).

---

## 8. Directory/File Layout

### New Files (Phase 21 Implementation)

```
research-pipeline/
├── services/
│   └── orchestrator/
│       ├── __init__.py          # Package init
│       ├── main.py              # OrchestratorHandler + main()
│       ├── pipeline.py          # Stage dispatch logic, retry, run tracking
│       └── scheduler.py         # APScheduler cron setup
├── Dockerfile                   # Multi-stage build (shared by all services)
├── docker-compose.yml           # All 6 services
└── .env                         # dotenvx encrypted secrets (GEMINI_API_KEY)
```

### Module Responsibilities

**`services/orchestrator/main.py`** (~120 LOC):
- `OrchestratorHandler(BaseHandler)` with routes: `/run`, `/status`, `/status/services`
- `main()`: init DB, create scheduler, start service

**`services/orchestrator/pipeline.py`** (~200 LOC):
- `PipelineRunner` class: dispatch logic, retry, result tracking
- `dispatch_stage()`: call service `/process` with retry
- `determine_next_stages()`: given paper's current stage, return stages to execute
- `generate_run_id()`: timestamp-based run ID
- `get_pipeline_status()`: aggregate DB query for `/status` endpoint

**`services/orchestrator/scheduler.py`** (~50 LOC):
- `create_scheduler()`: configure APScheduler `BackgroundScheduler`
- `cron_run()`: triggered by scheduler, calls `PipelineRunner`

### Existing Files (No Changes)

All 5 existing services and the shared library remain unchanged. The orchestrator consumes their HTTP APIs without any modifications.

---

## Service Contract Reference

### Discovery (port 8770)

```
POST /process
Request:  {"query": str, "max_results": int}
Response: {"papers_found": int, "papers_new": int, "papers_enriched_s2": int,
           "papers_enriched_cr": int, "errors": [str], "time_ms": int}
Stage:    (none) → discovered
External: arXiv API, Semantic Scholar API, CrossRef API
DB Write: papers table (INSERT/UPDATE)
```

### Analyzer (port 8771)

```
POST /process
Request:  {"paper_id": int?, "max_papers": int?, "force": bool?}
Response: {"papers_analyzed": int, "papers_accepted": int, "papers_rejected": int,
           "avg_score": float, "llm_provider": str?, "prompt_version": str,
           "errors": [str], "time_ms": int}
Stage:    discovered → analyzed | rejected
External: Gemini API (fallback), Ollama (localhost:11434)
DB Write: papers table (UPDATE stage, score)
```

### Extractor (port 8772)

```
POST /process
Request:  {"paper_id": int?, "max_papers": int?, "force": bool?}
Response: {"success": bool, "service": "extractor", "papers_processed": int,
           "formulas_extracted": int, "papers_failed": int, "errors": [str],
           "time_ms": int}
Stage:    analyzed → extracted (papers), creates formulas at stage='extracted'
External: arXiv export (PDF download), RAGAnything (localhost:8767)
DB Write: papers table (UPDATE stage), formulas table (INSERT)
```

### Validator (port 8773)

```
POST /process
Request:  {"paper_id": int?, "formula_id": int?, "max_formulas": int?,
           "force": bool?, "engines": [str]?}
Response: {"success": bool, "service": "validator", "formulas_processed": int,
           "formulas_valid": int, "formulas_invalid": int, "formulas_partial": int,
           "formulas_unparseable": int, "formulas_failed": int,
           "errors": [str], "time_ms": int, "details": [...]?}
Stage:    extracted → validated (formulas)
External: CAS microservice (localhost:8769)
DB Write: formulas table (UPDATE stage), validations table (INSERT)
```

### Codegen (port 8774)

```
POST /process
Request:  {"paper_id": int?, "formula_id": int?, "max_formulas": int?,
           "force": bool?}
Response: {"success": bool, "service": "codegen", "formulas_processed": int,
           "code_generated": {"c99": int, "rust": int, "python": int},
           "explanations_generated": int, "errors": [str], "time_ms": int}
Stage:    validated → codegen (formulas)
External: Ollama (localhost:11434), Gemini API (fallback)
DB Write: formulas table (UPDATE stage, description), generated_code table (INSERT)
```

---

*End of DESIGN.md — Phase 20, v7.0 Orchestrator + Deploy*
