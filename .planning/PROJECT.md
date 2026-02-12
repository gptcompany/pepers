# Research Pipeline

## What This Is

A set of 5 standalone Python microservices + 1 orchestrator that replaces the N8N W1-W5 research paper pipeline. Fetches academic papers from arXiv, enriches with citation data, analyzes with LLM, extracts formulas, validates with multi-CAS consensus, and generates Python/Rust code. Managed by systemd, monitored by the existing monitoring-stack (Prometheus + Grafana + Loki).

## Core Value

Reliable, N8N-free academic paper processing pipeline that discovers Kelly criterion papers, validates mathematical formulas with multiple CAS engines, and generates production code — all as independent, replaceable microservices.

## Requirements

### Validated

- ✓ Shared library: DB connection pool, Pydantic models, base HTTP server, config management — v1.0
- ✓ Each service exposes /health, /status, /process endpoints — v1.0
- ✓ dotenvx secret management aligned with SSOT at /media/sam/1TB/.env — v1.0

### Active

- [ ] Discovery service: fetch arXiv papers by keywords + enrich via Semantic Scholar/CrossRef
- [ ] Analyzer service: LLM analysis (Ollama qwen3:8b) + 5-criteria relevance scoring + routing
- [ ] Extractor service: send PDFs to RAGAnything + regex-based LaTeX formula extraction
- [ ] Validator service: multi-CAS validation (SymPy, Wolfram, Maxima) with consensus scoring
- [ ] Codegen service: LLM plain-language explanation + Python codegen (SymPy) + Rust codegen (AST-based)
- [ ] Orchestrator: coordinates pipeline stages, retry logic, error handling, Discord notifications
- [ ] systemd unit files for all 6 services + daily timer (8AM)
- [ ] Monitoring integration: process-exporter config, Prometheus alert rules, Grafana dashboard

### Out of Scope

- CAS microservice migration — already standalone systemd service at :8769, stays in N8N_dev
- RAGAnything migration — already standalone systemd service at :8767, stays in N8N_dev
- N8N decommissioning — separate task after pipeline proven working
- Web UI/dashboard — Grafana handles visualization
- Message queue (Redis/RabbitMQ) — HTTP sync is sufficient for daily batch
- Docker containerization — systemd native services, no Docker overhead
- Cross-server deployment — all services run on Workstation (192.168.1.111)

## Context

**Current state (v1.0 shipped):**
- Shared library: 816 LOC Python across 4 modules (db.py, models.py, server.py, config.py)
- SQLite schema: 5 tables, 6 indexes, WAL mode
- 8 Pydantic models with JSON field validators
- Base HTTP server with @route decorator, JSON logging, SIGTERM handling
- 103 tests, 98% coverage, 0 type errors
- Tech stack: Python stdlib (http.server, sqlite3, logging, json) + Pydantic

**Origin**: N8N crashed in Jan 2026, external team restored 88 workflows but lost all data. The W1-W5 pipeline (17 N8N workflows) never successfully processed a paper end-to-end — all tables empty, 0 executions. Rather than fix N8N, rebuilding as standalone microservices eliminates the single point of failure.

**Existing services that continue working independently**:
- CAS Microservice (:8769) — systemd user service, 1,090 LOC, only Maxima engine works (SageMath/MATLAB broken)
- RAGAnything (:8767) — systemd system service, 1,100 LOC, 743MB RAM, LightRAG + OpenAI/Ollama
- Ollama — local LLM (qwen3:8b) on localhost:11434
- PostgreSQL — N8N's postgres container (n8n-postgres-1), tables in public schema

**Monitoring stack** (`/media/sam/1TB/monitoring-stack/`):
- Prometheus (:9090) + node_exporter + process-exporter + alertmanager
- Grafana (:3000) with 3 dashboards + Grafana Cloud for critical alerts
- Loki (:3100) + Promtail — centralized logs (local only)
- QuestDB (:9000) — cron job metrics
- Discord webhook alerts

**Key findings from N8N pipeline analysis**:
- W5.3 Rust codegen was naive regex JS → needs proper AST approach
- Schema bug: queries referenced `finance_papers` schema but tables are in `public`
- CAS port: both SageMath and MATLAB share :8769 (correct, single service with `cas` parameter)
- Wolfram Alpha API key was hardcoded in N8N workflow JSON

**Pipeline data flow**: arXiv API → Semantic Scholar + CrossRef → Ollama LLM → RAGAnything → LaTeX regex → CAS consensus → SymPy codegen → Rust transpiler → Discord summary

## Constraints

- **Tech stack**: Python stdlib `http.server` (same pattern as existing CAS microservice). No frameworks.
- **Database**: SQLite with WAL mode (YAGNI — ~10 papers/day batch, zero infra overhead)
- **Secrets**: dotenvx encrypted, aligned with SSOT `/media/sam/1TB/.env`
- **Process mgmt**: systemd (native, journald → Loki integration)
- **LLM**: Ollama qwen3:8b (local, free, already deployed)
- **Ports**: 8770-8775 (non-conflicting with existing services)
- **Dependencies**: External services are existing (CAS :8769, RAGAnything :8767, Ollama :11434)
- **KISS/YAGNI**: No abstractions beyond immediate needs. No message queues, no Docker, no frameworks.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| http.server over FastAPI/Flask | Match CAS microservice pattern, zero extra deps, KISS | ✓ Good |
| Microservices over monolith | User chose for resilience + independent replaceability | — Pending |
| systemd over PM2/process-compose | Native Linux, journald → Loki, no extra deps | — Pending |
| Single venv for all services | Shared deps (pydantic), simpler management | ✓ Good |
| AST-based Rust codegen over regex | Original W5.3 was naive regex JS, quality was insufficient | — Pending |
| Keep CAS/RAG in N8N_dev | Already working as standalone systemd services, no need to move | ✓ Good |
| HTTP sync over async queue | Daily batch of ~10 papers, queue overhead not justified (YAGNI) | — Pending |
| SQLite over PostgreSQL | YAGNI — ~10 papers/day, zero infra overhead | ✓ Good |
| @route decorator dispatch | Clean route registration vs monolithic do_POST | ✓ Good |
| RP_ env var prefix | Namespace isolation for config | ✓ Good |
| WAL mode SQLite | Concurrent reads during batch processing | ✓ Good |
| JSON structured logging | Loki/journald parsing | ✓ Good |
| Warn + default for missing env vars | Development-friendly | ✓ Good |

---
*Last updated: 2026-02-12 after v1.0 milestone*
