# Context: Phase 45 — Docker Production Hardening

## Phase Goal

PePeRS Docker deployment is production-grade — survives reboots, limits resource usage, rotates logs, and shuts down cleanly.

## Requirements

- **DEP-01**: Log rotation — no single container log exceeds 10MB (json-file driver, 3 rotated files)
- **DEP-02**: Memory limits — 512MB per service, 1GB for orchestrator; container killed if exceeded
- **DEP-03**: Auto-start — all PePeRS containers running after Workstation reboot without manual intervention
- **DEP-04**: Graceful shutdown — `docker compose down` completes within 30 seconds with no orphaned processes

## Current State Analysis

### docker-compose.yml (single file, all 7 services)

- **Services**: discovery (8770), analyzer (8771), extractor (8772), validator (8773), codegen (8774), orchestrator (8775), mcp (8776)
- **Restart policy**: `restart: unless-stopped` on all services (handles Docker daemon restart, NOT host reboot)
- **Health checks**: All present with 30s interval, 5s timeout, 3 retries, 15s start_period
- **Network**: `network_mode: host` (required for localhost access to CAS:8769, RAG:8767, Ollama:11434)
- **Volumes**: `./data:/data` for SQLite, some mount host Node.js for Gemini CLI
- **User**: `1000:1000` (non-root)
- **Missing**: NO logging config, NO memory limits, NO stop_grace_period, NO systemd unit for Docker Compose auto-start

### Dockerfile (multi-stage)

- python:3.12-slim base
- Single `CMD ["sh", "-c", "python -m services.${SERVICE_NAME}.main"]`
- Proper multi-stage (builder → runtime)
- No STOPSIGNAL override (default SIGTERM is fine — shared/server.py handles SIGTERM via signal handler)

### SIGTERM Handling (already implemented in Phase 43)

- `shared/server.py` registers SIGTERM handler that calls `server.shutdown()`
- `daemon_threads=True` on ThreadingHTTPServer ensures active request threads die when main thread exits
- Python process exits cleanly on SIGTERM

### Docker Environment

- Docker 29.2.1, Compose v5.0.2
- Workstation: 192.168.1.111 (Ubuntu 22.04)
- No PePeRS containers currently running
- No existing systemd units for PePeRS

### Monitoring Stack (reference)

- Located at `/media/sam/1TB/monitoring-stack/`
- Already has its own docker-compose.yml with Prometheus, Grafana, Loki
- Phase 46 will integrate PePeRS metrics into this stack
- PePeRS and monitoring stack are SEPARATE Docker Compose projects

## What Needs to Change

### 1. Logging + Memory via YAML Extension Fields (DEP-01, DEP-02 — DRY)

Use Compose extension fields (`x-`) and YAML anchors to avoid repeating config in 7 services:

```yaml
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

x-deploy-service: &default-deploy
  resources:
    limits:
      memory: 512m

x-deploy-orchestrator: &orchestrator-deploy
  resources:
    limits:
      memory: 1g
```

Each service references `logging: *default-logging` and `deploy: *default-deploy`. Orchestrator uses `deploy: *orchestrator-deploy`.

Note: `deploy.resources` in Docker Compose v2+ (non-Swarm) requires `docker compose` CLI. Verified: Compose v5.0.2 supports this.

### 2. Auto-start (DEP-03)

`restart: unless-stopped` already survives host reboots IF Docker daemon is enabled via systemd (`systemctl enable docker`). Verification needed:
```bash
systemctl is-enabled docker  # should be "enabled"
```

If Docker daemon is systemd-enabled, `restart: unless-stopped` handles both daemon restarts AND host reboots. A dedicated systemd unit for `docker compose up` is REDUNDANT in this case.

**Decision**: Verify Docker daemon is systemd-enabled. If yes, `restart: unless-stopped` is sufficient for DEP-03. If no, either `systemctl enable docker` or add a systemd unit.

Systemd unit structure (only if needed):
```ini
[Unit]
Description=PePeRS Docker Compose
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/media/sam/1TB/pepers
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

### 3. Graceful Shutdown (DEP-04)

`docker compose down` sends SIGTERM to all containers, waits `stop_grace_period`, then SIGKILL.
DEP-04 requires total down time < 30s.

- Regular services: `stop_grace_period: 10s` (Python SIGTERM handler exits in <1s)
- Orchestrator: `stop_grace_period: 20s` (may be mid-pipeline, needs to mark run as failed)
- Total worst-case: 20s (all containers stop in parallel) — well within 30s requirement

## Risks

1. **Memory limit too aggressive**: 512MB may be tight for extractor (PDF download + RAGAnything response) — but extractor doesn't hold PDF in memory, streams to disk (LOW)
2. **Docker OOM behavior**: Container killed by OOM killer, loses in-flight work — acceptable, restart policy handles it (LOW)
3. **Log rotation on existing containers**: Requires `docker compose up -d --force-recreate` to apply new logging config to running containers (LOW)
4. **Docker daemon not enabled**: If `systemctl is-enabled docker` returns "disabled", containers won't auto-start after host reboot (MEDIUM — check and fix)

## Success Criteria (from ROADMAP.md)

1. After 24h of operation, no single container log file exceeds 10MB (json-file driver, 3 rotated files)
2. A container that allocates excessive memory is killed by Docker (512MB limit per service, 1GB for orchestrator)
3. After Workstation reboot, `docker ps` shows all PePeRS containers running without manual intervention
4. `docker compose down` completes within 30 seconds with no orphaned processes
