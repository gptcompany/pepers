# Research Summary: v13.0 Production Hardening

## Key Findings

### Stack Additions
- **prometheus-client** (pypi, ~60KB) — only new dependency. Exposes `/metrics` on each service.
- **ThreadingHTTPServer** — stdlib, zero new deps. Replaces `HTTPServer` in `shared/server.py`.
- Everything else is config changes to existing infrastructure.

### Architecture Integration
- `shared/server.py` is the single change point for threading + body limits + metrics — affects all 6 microservices.
- MCP server (`services/mcp/`) uses `FastMCP` SDK with its own HTTP handling — NOT affected by `shared/server.py` changes. MCP concurrency depends on the `mcp` SDK (likely already async/threaded).
- Monitoring stack at `/media/sam/1TB/monitoring-stack/` needs config additions: process-exporter rules, Prometheus scrape job, Grafana dashboard JSON.
- Docker Compose needs: log rotation, resource limits, systemd unit for auto-start.

### Feature Table Stakes
1. ThreadingHTTPServer for concurrent requests (all 6 services)
2. Request body size limit (10MB default)
3. Stuck-state cleanup at orchestrator startup
4. Docker log rotation (`json-file`, 10m × 3)
5. Prometheus `/metrics` endpoint per service
6. Grafana dashboard (6 panels: health, throughput, latency, errors, formula results, runs)
7. Prometheus alerts (service down, pipeline stalled, high error rate)
8. process-exporter rules for PePeRS services
9. systemd unit for Docker Compose auto-start at boot

### Watch Out For
1. **SQLite thread safety** (HIGH): Verify `get_connection()` is per-request in all services, never cached. ThreadingHTTPServer = concurrent threads = each needs its own connection.
2. **Prometheus label cardinality**: NEVER use paper_id/formula_id as labels. Bounded labels only.
3. **MCP SSE + threading**: MCP server uses its own SDK, threading change doesn't apply to it. MCP concurrency is already handled by FastMCP.
4. **Stuck-state race condition**: Add stale threshold (>5 min) before marking runs as failed.
5. **Docker log rotation**: Requires `--force-recreate` to take effect on existing containers.

### Build Order (dependency-driven)
1. Threading + body size limit (shared/server.py) — foundation for all services
2. Stuck-state cleanup (orchestrator) — standalone
3. Prometheus metrics (shared/server.py + per-service) — depends on step 1
4. Docker hardening (docker-compose.yml) — independent
5. Monitoring integration (process-exporter, Prometheus, Grafana) — depends on step 3
6. E2E testing — depends on all above
