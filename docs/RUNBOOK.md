# PePeRS -- Operational Runbook

Production operations guide for the 6-service research paper processing pipeline.

## 1. Service Overview

| Service | Port | Description | External Dependencies |
|---------|------|-------------|-----------------------|
| discovery | 8770 | arXiv/Semantic Scholar/CrossRef paper search | arXiv API, S2 API, CrossRef API |
| analyzer | 8771 | Topic-agnostic LLM scoring (5 criteria, 0-1.0 scale) | LLM fallback chain |
| extractor | 8772 | PDF to LaTeX formula extraction | RAGAnything (:8767) |
| validator | 8773 | CAS mathematical validation (multi-engine consensus) | CAS engine (:8769), SymPy |
| codegen | 8774 | 5-layer LaTeX→code (C99/Rust/Python) + batch LLM explain | LLM fallback chain, SymPy |
| orchestrator | 8775 | Pipeline coordination, batch iteration, status API | All above services |

**Database**: SQLite (WAL mode), schema v4, shared across all services.

**Pipeline flow**: discovery -> analyzer -> extractor -> validator -> codegen

## 2. Prerequisites

- Python 3.11+
- SQLite 3.35+ (WAL mode, RETURNING clause)
- RAGAnything server on port 8767 (PDF processing)
- CAS validation server on port 8769 (SymPy, Maxima, MATLAB engines)
- At least one LLM provider:
  - **Ollama** (recommended for local): default fallback
  - **OpenRouter**: requires `OPENROUTER_API_KEY`
  - **Gemini**: requires `GEMINI_API_KEY` or Gemini CLI installed
- dotenvx for secret management (`.env` encrypted)

## 3. Startup Order

Services must start in dependency order. The orchestrator depends on all 5 downstream services.

### External Dependencies (start first)

```bash
# RAGAnything (PDF extraction backend)
# Ensure running on port 8767

# CAS validation engine
# Ensure running on port 8769

# Ollama (if using local LLM)
ollama serve
```

### Pipeline Services

**Option A: systemd (recommended for production)**

```bash
# Start all services in dependency order via target
sudo systemctl start rp-pipeline.target

# Or start individually
sudo systemctl start rp-discovery
sudo systemctl start rp-analyzer
sudo systemctl start rp-extractor
sudo systemctl start rp-validator
sudo systemctl start rp-codegen
sudo systemctl start rp-orchestrator
```

**Option B: Docker Compose**

```bash
cd /media/sam/1TB/pepers
docker compose up -d
```

**Option C: Manual (development)**

```bash
cd /media/sam/1TB/pepers
python -m services.discovery.main &
python -m services.analyzer.main &
python -m services.extractor.main &
python -m services.validator.main &
python -m services.codegen.main &
python -m services.orchestrator.main &
```

### Shutdown Order

Reverse of startup: orchestrator first, then downstream services.

```bash
sudo systemctl stop rp-pipeline.target
# or
docker compose down
```

## 4. Health Check URLs

All services expose `GET /health` returning JSON:

```json
{
  "status": "ok",
  "service": "<name>",
  "uptime_seconds": 3600,
  "db_ok": true,
  "schema_version": 4,
  "last_request_seconds_ago": 120
}
```

**Quick check all services:**

```bash
for port in 8770 8771 8772 8773 8774 8775; do
  echo -n "Port $port: "
  curl -sf http://localhost:$port/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['service'], d['status'])" 2>/dev/null || echo "DOWN"
done
```

**Orchestrator aggregate check:**

```bash
# Check all downstream services via orchestrator
curl -s http://localhost:8775/status/services | python3 -m json.tool
```

Response includes `all_healthy: true/false` and per-service status.

**Pipeline status (papers/formulas by stage):**

```bash
curl -s http://localhost:8775/status | python3 -m json.tool
```

## 5. Common Failure Modes

### 5.1 Service Crash During Batch Processing

**Symptom**: Service PID disappears, formulas stuck at intermediate stage.

**Cause**: OOM, uncaught exception, external kill.

**Impact**: Paper stage may be inconsistent with formula stages.

**Mitigation**: systemd `Restart=always` with `RestartSec=5` auto-restarts the service. Each service runs a consistency check at startup (`_check_consistency()`) that detects and resolves inconsistent states.

**Resolution**: Automatic. If the paper is stuck, see Recovery 6.1.

### 5.2 SQLite WAL Contention ("database is locked")

**Symptom**: HTTP 500 with "database is locked" in logs.

**Cause**: Multiple services writing simultaneously under heavy load. SQLite WAL allows concurrent reads but serializes writes.

**Impact**: Transient — requests fail but retry succeeds.

**Resolution**:
1. Usually self-resolving (WAL lock timeout is 5s default).
2. If persistent: stop all services, verify no stale WAL lock:
   ```bash
   ls -la data/research.db*
   # If .db-wal or .db-shm exist with stale locks:
   # Stop all services first, then restart.
   ```
3. Long-term: consider PostgreSQL migration for concurrent write loads.

### 5.3 External API Rate Limits

**arXiv API**: Max 3 requests/second. Discovery service inserts 1s delay between requests.

**Semantic Scholar**: 100 requests per 5 minutes (unauthenticated). Discovery retries with exponential backoff.

**CrossRef**: Generous limits (50 req/s with polite pool). Rarely an issue.

**Symptom**: Discovery service returns HTTP 429 or connection timeouts.

**Resolution**: Wait and retry. Reduce `max_papers` parameter. For heavy usage, consider S2 API key for higher limits.

### 5.4 CAS Engine Timeout

**Symptom**: Validator takes >17s/formula average, or times out entirely.

**Cause**: Complex LaTeX with nested expressions, or CAS engine (Maxima/MATLAB) hanging on edge cases.

**Impact**: Individual formulas marked as `failed`, pipeline continues with remaining formulas.

**Resolution**: Formula-level — no action needed (failed formulas are skipped). If CAS server itself is down, restart it on port 8769.

### 5.5 LLM Provider Unreachable

**Symptom**: Analyzer or codegen return connection errors or timeouts.

**Cause**: Ollama not running, OpenRouter API key expired, Gemini quota exhausted.

**Impact**: `fallback_chain()` automatically tries next provider in order. If all providers fail, the stage fails for that paper.

**Resolution**:
1. Check Ollama: `curl http://localhost:11434/api/tags`
2. Check OpenRouter: verify `OPENROUTER_API_KEY` in `.env`
3. Check Gemini: `gemini -p "test"` or verify `GEMINI_API_KEY`
4. Restart the failed provider and retry the pipeline run.

### 5.6 Extractor PDF Processing Failure

**Symptom**: Extractor timeout (>3600s on CPU) or crash.

**Cause**: Corrupted PDF, extremely large document (>100 pages), GPU OOM, or RAGAnything server unavailable.

**Impact**: Paper marked as `failed` at `extracted` stage.

**Resolution**:
1. Verify RAGAnything server: `curl http://localhost:8767/health`
2. Check logs: `journalctl -u rp-extractor -n 50`
3. For specific paper: reset and retry (see Recovery 6.1)
4. For persistent failures: increase `RP_EXTRACTOR_TIMEOUT` or use GPU

### 5.7 Codegen OOM Kill (Exit Code 137)

**Symptom**: Codegen service killed by OOM killer after processing many formulas. `journalctl` shows exit code 137.

**Cause**: Python's pymalloc doesn't return freed memory to the OS. SymPy expression trees and codegen ASTs accumulate heap fragmentation across formulas.

**Prevention**: Built-in `gc.collect()` + `malloc_trim(0)` runs after each formula. This forces Python to release freed heap back to the OS.

**Resolution**: If still OOM:
1. Reduce `RP_CODEGEN_MAX_FORMULAS` (e.g., 20 instead of 50)
2. Reduce `RP_CODEGEN_BATCH_SIZE` (e.g., 5 instead of 10)
3. Add systemd `MemoryMax=2G` to the codegen unit

### 5.8 Batch Explain Circuit Breaker

**Symptom**: Codegen produces code but with 0 explanations.

**Cause**: `explain_formulas_batch()` failed (LLM providers all timed out or returned errors). The circuit breaker skips all per-formula explain and proceeds directly to SymPy codegen.

**Impact**: Code is generated correctly. Only the `formulas.description` field is NULL for affected formulas.

**Resolution**: This is by design — no per-formula LLM fallback to avoid token waste and timeout cascading. To retry explanations:
1. Reset formula stage: `sqlite3 data/research.db "UPDATE formulas SET stage='validated' WHERE paper_id=<ID>;"`
2. Ensure LLM providers are available (check Ollama, OpenRouter, Gemini)
3. Re-run codegen via orchestrator

## 6. Recovery Procedures

### 6.1 Paper Stuck in Intermediate Stage

**Diagnosis:**

```bash
sqlite3 data/research.db "SELECT id, arxiv_id, stage, error FROM papers WHERE stage NOT IN ('codegen', 'rejected', 'failed');"
```

**Recovery:**

```bash
# Reset a specific paper to 'discovered' for full reprocessing
sqlite3 data/research.db "UPDATE papers SET stage = 'discovered', error = NULL WHERE id = <PAPER_ID>;"

# Trigger reprocessing via orchestrator
curl -X POST http://localhost:8775/run \
  -H "Content-Type: application/json" \
  -d '{"paper_id": <PAPER_ID>, "stages": 5}'
```

### 6.2 Duplicate Formula Detection

Schema v3 enforces `UNIQUE(paper_id, latex_hash)` on the formulas table, preventing duplicates. If duplicates exist from a pre-v3 database:

```bash
# Find duplicates
sqlite3 data/research.db "SELECT paper_id, latex_hash, COUNT(*) as cnt FROM formulas GROUP BY paper_id, latex_hash HAVING cnt > 1;"

# Remove duplicates (keep lowest ID)
sqlite3 data/research.db "DELETE FROM formulas WHERE id NOT IN (SELECT MIN(id) FROM formulas GROUP BY paper_id, latex_hash);"
```

### 6.3 Batch Iteration Safety Cap Hit

The orchestrator caps batch iterations at 100 (safety limit). If this cap is hit, formulas may remain unprocessed.

**Diagnosis:**

```bash
# Check formula stage distribution for a paper
sqlite3 data/research.db "SELECT stage, COUNT(*) FROM formulas WHERE paper_id = <PAPER_ID> GROUP BY stage;"
```

**Resolution**: Usually indicates a bug where formulas cycle between stages. Check service logs for the affected paper:

```bash
journalctl -u rp-validator --since "1 hour ago" | grep <PAPER_ID>
```

### 6.4 Full Pipeline Re-run (Async)

POST /run is **asynchronous** (HTTP 202). It returns immediately with a `run_id` and processes in the background. Poll GET /runs for status.

```bash
# Start async run
RUN_ID=$(curl -s -X POST http://localhost:8775/run \
  -H "Content-Type: application/json" \
  -d '{"query": "id:<ARXIV_ID>", "stages": 5, "force": true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")

echo "Run started: $RUN_ID"

# Poll for completion
while true; do
  STATUS=$(curl -s "http://localhost:8775/runs?id=$RUN_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Status: $STATUS"
  [ "$STATUS" != "running" ] && break
  sleep 5
done

# Get final results
curl -s "http://localhost:8775/runs?id=$RUN_ID" | python3 -m json.tool
```

### 6.5 Query Generated Code

```bash
# All generated code for a paper
curl -s "http://localhost:8775/generated-code?paper_id=42" | python3 -m json.tool

# Filter by language
curl -s "http://localhost:8775/generated-code?paper_id=42&language=python" | python3 -m json.tool

# Specific formula
curl -s "http://localhost:8775/generated-code?paper_id=42&formula_id=551" | python3 -m json.tool

# Pagination
curl -s "http://localhost:8775/generated-code?paper_id=42&limit=10&offset=20" | python3 -m json.tool
```

### 6.6 Database Backup and Restore

```bash
# Backup
cp data/research.db data/research.db.bak-$(date +%Y%m%d-%H%M%S)

# Restore (stop all services first!)
sudo systemctl stop rp-pipeline.target
cp data/research.db.bak-YYYYMMDD-HHMMSS data/research.db
sudo systemctl start rp-pipeline.target
```

## 7. Configuration Reference

All configuration via environment variables with `RP_` prefix. Set in `.env` (dotenvx encrypted).

### Service Ports

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_DISCOVERY_PORT` | 8770 | Discovery service port |
| `RP_ANALYZER_PORT` | 8771 | Analyzer service port |
| `RP_EXTRACTOR_PORT` | 8772 | Extractor service port |
| `RP_VALIDATOR_PORT` | 8773 | Validator service port |
| `RP_CODEGEN_PORT` | 8774 | Codegen service port |
| `RP_ORCHESTRATOR_PORT` | 8775 | Orchestrator service port |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_DB_PATH` | `data/research.db` | SQLite database path |
| `RP_DATA_DIR` | `data/` | Data directory for PDFs and cache |

### Orchestrator

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_ORCHESTRATOR_TIMEOUT` | 300 | Per-service HTTP call timeout (seconds; codegen uses 900 via `RP_ORCHESTRATOR_CODEGEN_TIMEOUT`) |
| `RP_ORCHESTRATOR_RETRY_MAX` | 3 | Max retries per service call |
| `RP_ORCHESTRATOR_RETRY_BACKOFF` | 4.0 | Exponential backoff base (seconds) |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_LLM_TEMPERATURE` | 0.0 | LLM temperature (0 = deterministic) |
| `RP_LLM_SEED` | 42 | LLM seed for reproducibility |
| `RP_LLM_FALLBACK_ORDER` | `gemini_cli,codex_cli,claude_cli,openrouter,ollama` | Comma-separated provider fallback order |
| `RP_CODEGEN_FALLBACK_ORDER` | (same as above) | Codegen-specific override; falls back to `RP_LLM_FALLBACK_ORDER` |

### CLI Providers

CLI LLM providers are data-driven via `shared/cli_providers.json`. Available providers:

| Provider | CLI Command | Default Model | Timeout Env |
|----------|-------------|---------------|-------------|
| `claude_cli` | `claude --print` | sonnet | `RP_LLM_TIMEOUT_CLAUDE_CLI` (120s) |
| `codex_cli` | `npx @openai/codex exec` | o4-mini | `RP_LLM_TIMEOUT_CODEX_CLI` (120s) |
| `gemini_cli` | `gemini -p` | (default) | `RP_LLM_TIMEOUT_GEMINI_CLI` (120s) |

**Configuration:**

```bash
# Set custom fallback order (tried left-to-right, first success wins)
RP_LLM_FALLBACK_ORDER=gemini_cli,codex_cli,claude_cli,openrouter,ollama

# Override timeout for a specific provider
RP_LLM_TIMEOUT_CLAUDE_CLI=180
```

**Adding a new CLI provider:** Edit `shared/cli_providers.json` — no Python changes needed. Required fields: `cmd`, `input_mode` ("stdin" or "arg"), `output_format`, `default_timeout`.

### Batch Processing

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_MAX_FORMULAS` | 50 | Max formulas per validator/codegen batch |
| `RP_CODEGEN_BATCH_SIZE` | 10 | Formulas per batch explain LLM call (clamped 5-25) |

### Analyzer

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_ANALYZER_TOPIC` | `Kelly criterion, optimal bet sizing, fractional Kelly, portfolio optimization` | Scoring topic (topic-agnostic) |
| `RP_ANALYZER_THRESHOLD` | 0.7 | Min avg_score to pass analysis (0.0-1.0) |

### Codegen

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_CODEGEN_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL for codegen |
| `RP_CODEGEN_MAX_FORMULAS` | 50 | Max formulas per codegen run |
| `RP_ORCHESTRATOR_CODEGEN_TIMEOUT` | 900 | Codegen stage timeout in seconds (vs 300 for other stages) |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_LOG_LEVEL` | INFO | Log level (DEBUG, INFO, WARNING, ERROR) |
| `RP_HOST` | 0.0.0.0 | Service bind address |

## 8. Extractor Performance Notes

The extractor service uses RAGAnything (built on MinerU) for PDF processing. Performance varies significantly based on hardware.

### Expected Processing Times

| Hardware | Time per Page | 10-page Paper | 50-page Paper |
|----------|--------------|---------------|---------------|
| CPU (Intel i7) | ~10 min | ~100 min | ~500 min |
| GPU (NVIDIA RTX) | ~1 min | ~10 min | ~50 min |

### Recommended Timeout Values

| Environment | `RP_EXTRACTOR_TIMEOUT` |
|-------------|----------------------|
| GPU (production) | 600 |
| CPU (development) | 3600 |
| CPU (large papers) | 7200 |

### First-Run Model Download

RAGAnything downloads ML models (~2GB) on first execution. Subsequent runs use the cached models. Ensure adequate disk space in the data directory.

### Memory Requirements

- **Minimum**: 4GB RAM for PDF processing
- **Recommended**: 8GB+ RAM for large papers (>50 pages)
- **GPU**: 4GB+ VRAM (NVIDIA CUDA required)

### Pre-caching

For production deployments, run the extractor once on a small paper to trigger model downloads before processing real workloads:

```bash
curl -X POST http://localhost:8772/process \
  -H "Content-Type: application/json" \
  -d '{"paper_id": 1, "max_papers": 1}'
```

## 9. Monitoring

### Log Locations

**systemd services:**

```bash
# Follow all pipeline logs
journalctl -u "rp-*" -f

# Specific service
journalctl -u rp-validator -n 100 --no-pager

# Since specific time
journalctl -u rp-orchestrator --since "2 hours ago"
```

**Docker Compose:**

```bash
docker compose logs -f orchestrator
docker compose logs --tail=100 validator
```

### Key Metrics

**Pipeline throughput:**

```bash
# Papers processed in last 24h
sqlite3 data/research.db "SELECT COUNT(*) FROM papers WHERE updated_at > datetime('now', '-1 day');"

# Formulas processed in last 24h
sqlite3 data/research.db "SELECT stage, COUNT(*) FROM formulas WHERE updated_at > datetime('now', '-1 day') GROUP BY stage;"
```

**Error rate:**

```bash
# Recent errors
sqlite3 data/research.db "SELECT id, arxiv_id, stage, error FROM papers WHERE error IS NOT NULL ORDER BY updated_at DESC LIMIT 10;"

# Formula failure rate
sqlite3 data/research.db "SELECT ROUND(100.0 * SUM(CASE WHEN stage = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS failure_pct FROM formulas;"
```

**Service uptime:**

```bash
curl -s http://localhost:8775/status/services | python3 -c "
import json, sys
d = json.load(sys.stdin)
for name, info in d['services'].items():
    status = info.get('status', 'unknown')
    uptime = info.get('uptime_seconds', 0)
    print(f'{name:15s} {status:5s} uptime={uptime:.0f}s')
"
```

### Smoke Test

Run the full pipeline smoke test to verify end-to-end health:

```bash
# Direct mode (calls each service individually)
python scripts/smoke_test.py

# Via orchestrator (async POST /run + poll GET /runs)
python scripts/smoke_test.py --via-orchestrator

# Quick test with fewer formulas
python scripts/smoke_test.py --via-orchestrator --max-formulas 5
```

Exit code 0 = all stages passed, final stage = codegen.
