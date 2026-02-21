# Pitfalls Research: Production Hardening

## P1: ThreadingHTTPServer + SQLite Thread Safety

**Risk:** HIGH
**Phase:** Concurrency

SQLite connections are NOT thread-safe across threads. With `ThreadingHTTPServer`, each request runs in a new thread. If any service caches a SQLite connection at module level or class level, concurrent requests will corrupt data or crash.

**Current code review:**
- `shared/db.py` `get_connection()` creates a new connection each call — GOOD.
- BUT: check if any service stores `conn` as instance variable and reuses across requests.
- `check_constraints=False` on connections means SQLite won't enforce foreign keys by default — unrelated but worth noting.

**Prevention:**
- Verify every `get_connection()` call is per-request (in handler method), never cached.
- Add `check_same_thread=False` to `sqlite3.connect()` only if needed (it shouldn't be with per-request connections).
- Test: concurrent requests to same endpoint, verify no "ProgrammingError: SQLite objects created in a thread can only be used in that same thread."

## P2: Docker Log Rotation — Existing Logs

**Risk:** MEDIUM
**Phase:** Deployment

Adding `logging.options.max-size` to docker-compose.yml only affects NEW containers. Existing containers keep their current log driver config. If containers are already running with no rotation, their logs remain unbounded until the container is recreated.

**Prevention:**
- After changing docker-compose.yml, run `docker compose up -d --force-recreate` (not just `docker compose up -d`).
- Check existing log sizes first: `du -sh /var/lib/docker/containers/*/`

## P3: Prometheus Metrics Cardinality

**Risk:** MEDIUM
**Phase:** Monitoring

Adding labels like `paper_id` or `formula_id` to Prometheus metrics creates HIGH cardinality (unbounded). VictoriaMetrics handles this better than vanilla Prometheus, but it still wastes storage and slows queries.

**Prevention:**
- NEVER use paper IDs, formula IDs, or arxiv IDs as metric labels.
- Use bounded labels only: `service`, `stage`, `error_type`, `status_code`, `engine`.
- Max cardinality estimate: 7 services × 5 endpoints × 5 status codes = 175 series. Acceptable.

## P4: Health Check + ThreadingHTTPServer Interaction

**Risk:** LOW
**Phase:** Concurrency

Docker health checks hit `/health` every 30s. With `HTTPServer` (single-threaded), a long-running `/process` request blocks health checks, making Docker think the service is unhealthy and restart it.

**ThreadingHTTPServer fixes this** — health checks run in their own thread. But if all threads are busy (thread pool exhausted), health checks still fail.

**Prevention:**
- Default `ThreadingHTTPServer` has no thread limit (creates threads on demand) — fine for PePeRS traffic.
- If needed later: subclass with `ThreadPoolExecutor` for bounded pool.

## P5: SSE Connection Lifetime with Threading

**Risk:** MEDIUM
**Phase:** Concurrency

The MCP server uses Server-Sent Events (SSE) — long-lived HTTP connections. With `ThreadingHTTPServer`, each SSE connection pins a thread for its entire lifetime. Multiple MCP clients = multiple pinned threads.

**Prevention:**
- With 2-3 MCP clients, this means 2-3 permanent threads. Acceptable.
- The MCP server (`services/mcp/`) may use the `mcp` SDK which has its own server — verify if it even uses `shared/server.py` or has its own HTTP handling.

## P6: Stuck-State Cleanup Race Condition

**Risk:** MEDIUM
**Phase:** Resilience

If orchestrator crashes mid-pipeline and restarts, the startup cleanup marks all "running" pipeline_runs as "failed". But if Docker restart is fast and the pipeline was processing a request that another service is still handling, marking it failed while processing continues leads to inconsistent state.

**Prevention:**
- Cleanup only affects `pipeline_runs` table, not individual paper stages.
- Paper stages are updated by individual services — they'll either succeed or fail independently.
- Add a timestamp check: only mark as failed if `started_at` is > 5 minutes ago (stale threshold).

## P7: network_mode: host and Port Conflicts

**Risk:** LOW
**Phase:** Deployment

With `network_mode: host`, all PePeRS services bind to host ports 8770-8776. If any other process starts on those ports, PePeRS containers fail to start.

**Prevention:**
- Ports 8770-8776 are already reserved for PePeRS. Document in RUNBOOK.md.
- Health check startup failures will trigger restart, which is fine for transient conflicts.

## P8: Grafana Dashboard Version Conflicts

**Risk:** LOW
**Phase:** Monitoring

Provisioned dashboards are read-only in Grafana. If someone manually edits the dashboard in the UI, changes are lost on next Grafana restart (provisioning overwrites).

**Prevention:**
- This is the intended behavior. All changes go through `pepers.json` file.
- Use `"editable": false` in dashboard JSON to make this explicit.
