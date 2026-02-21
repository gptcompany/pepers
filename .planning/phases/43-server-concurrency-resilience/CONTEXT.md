# Context: Phase 43 — Server Concurrency + Resilience

## Phase Goal

All PePeRS services handle concurrent requests safely, reject oversized payloads, and recover from stuck pipeline states on restart.

## Requirements

- **CONC-01**: All 6 microservices handle concurrent requests via ThreadingHTTPServer
- **CONC-02**: Request body size is limited to 10MB with 413 error on exceeding
- **CONC-03**: SQLite connections are verified thread-safe (per-request, no caching)
- **RES-01**: Orchestrator startup cleans stuck pipeline_runs (running >5min → failed with reason)

## Current State Analysis

### shared/server.py (single change point for CONC-01, CONC-02)

- Uses `HTTPServer` from `http.server` (line 318) — single-threaded, blocks on long requests
- `BaseService` class wraps HTTPServer: `self.server = HTTPServer(("0.0.0.0", self.port), self.handler)`
- `BaseHandler` extends `BaseHTTPRequestHandler` with route dispatch, JSON helpers, `/health`, `/status`
- **Thread safety issue**: `last_request_time` set at class level (line 119) without locking
- No body size limit currently — any payload size accepted
- Graceful SIGTERM handling via signal handler (line 306-310)

**Change needed**: Replace `HTTPServer` with `ThreadingHTTPServer`, add body size check in `do_POST`, add threading lock for shared state.

### shared/db.py (CONC-03 verification)

- `get_connection()` creates a NEW `sqlite3.Connection` per call — no caching, no pooling
- WAL mode enabled: `PRAGMA journal_mode=WAL`
- Busy timeout 5s: `PRAGMA busy_timeout=5000`
- Foreign keys ON
- Context manager pattern with auto commit/rollback

**Assessment**: Already thread-safe by design. Each handler call gets its own connection. WAL allows concurrent reads. Just need to verify no service caches connections.

### 6 Microservices (all use BaseService)

| Service | Port | Main File |
|---------|------|-----------|
| discovery | 8770 | services/discovery/main.py |
| analyzer | 8771 | services/analyzer/main.py |
| extractor | 8772 | services/extractor/main.py |
| validator | 8773 | services/validator/main.py |
| codegen | 8774 | services/codegen/main.py |
| orchestrator | 8775 | services/orchestrator/main.py |

All follow: `BaseService("name", PORT, Handler, db_path).run()`

### Orchestrator Pipeline Run Tracking (RES-01)

- `pipeline_runs` table: run_id, status, params, results, errors, stages_completed, stages_requested, started_at, completed_at
- Status values: 'running', 'completed', 'partial', 'failed'
- Stuck runs = status='running' with started_at > 5 min ago and no completed_at
- Pipeline runner in `services/orchestrator/pipeline.py` (PipelineRunner class)

### Docker Compose

- All services use `network_mode: host`
- Single shared SQLite: `/data/research.db`
- Health checks: `GET /health` (30s interval)
- Dependency chain: discovery → analyzer → extractor → validator → codegen → orchestrator → mcp

## Decisions (from v13.0 research)

- ThreadingHTTPServer over async (stdlib, zero deps, matches existing pattern)
- prometheus-client is only new dependency (~60KB) — Phase 44, not 43
- shared/server.py is single change point for threading + body limits
- MCP server (FastMCP SDK) NOT affected by shared/server.py changes

## Risks

1. **SQLite thread safety**: Need to audit all services for connection caching (HIGH)
2. **Handler class state**: `last_request_time` needs threading.Lock (MEDIUM)
3. **Stuck-state race condition**: Must use stale threshold (>5 min) not just status='running' (MEDIUM)
4. **Thread pool exhaustion**: ThreadingHTTPServer spawns unlimited threads per request — must cap with ThreadPoolExecutor or max threads (MEDIUM)
5. **Body size check order**: MUST check Content-Length header BEFORE reading rfile stream to prevent memory exhaustion DoS (HIGH)
6. **SQLite write serialization**: WAL allows concurrent reads but writes are still serialized at file level — acceptable for ~10 papers/day batch but note as limitation (LOW)
7. **Stuck timeout flexibility**: 5 min threshold may be aggressive for long LLM/codegen operations — make configurable via env var (LOW)

## Success Criteria (from ROADMAP.md)

1. Two concurrent HTTP requests to any service both receive correct responses
2. >10MB body request → HTTP 413, server continues
3. Each thread gets its own SQLite connection — no ProgrammingError
4. After kill+restart orchestrator, stuck "running" record → "failed" with reason
