# Research Pipeline

## What This Is

A set of 5 standalone Python microservices + 1 orchestrator that replaces the N8N W1-W5 research paper pipeline. Fetches academic papers from arXiv, enriches with citation data, analyzes with LLM, extracts formulas, validates with multi-CAS consensus, and generates Python/Rust code. Deployed via Docker Compose on Workstation, monitored by the existing monitoring-stack (Prometheus + Grafana + Loki).

## Core Value

Reliable, N8N-free academic paper processing pipeline that discovers Kelly criterion papers, validates mathematical formulas with multiple CAS engines, and generates production code — all as independent, replaceable microservices.

## Requirements

### Validated

- ✓ Shared library: DB connection pool, Pydantic models, base HTTP server, config management — v1.0
- ✓ Each service exposes /health, /status, /process endpoints — v1.0
- ✓ dotenvx secret management aligned with SSOT at /media/sam/1TB/.env — v1.0
- ✓ Discovery service: fetch arXiv papers by keywords + enrich via Semantic Scholar/CrossRef — v2.0
- ✓ Analyzer service: LLM analysis (triple fallback) + 5-criteria relevance scoring + routing — v3.0
- ✓ Extractor service: PDF download + RAGAnything text extraction + 5-pass LaTeX regex + formula storage — v4.0
- ✓ Validator service: multi-CAS validation (SymPy + Maxima + MATLAB) with all-or-nothing consensus — v5.0
- ✓ Codegen service: LLM plain-language explanation + C99/Rust/Python codegen via SymPy — v6.0

### Active
- [ ] Monitoring integration: process-exporter config, Prometheus alert rules, Grafana dashboard
- [ ] Production deployment: `docker compose up` on Workstation

### Validated

- ✓ Shared library: DB connection pool, Pydantic models, base HTTP server, config management — v1.0
- ✓ Each service exposes /health, /status, /process endpoints — v1.0
- ✓ dotenvx secret management aligned with SSOT at /media/sam/1TB/.env — v1.0
- ✓ Discovery service: fetch arXiv papers by keywords + enrich via Semantic Scholar/CrossRef — v2.0
- ✓ Analyzer service: LLM analysis (triple fallback) + 5-criteria relevance scoring + routing — v3.0
- ✓ Extractor service: PDF download + RAGAnything text extraction + 5-pass LaTeX regex + formula storage — v4.0
- ✓ Validator service: multi-CAS validation (SymPy + Maxima + MATLAB) with fallback consensus — v5.0
- ✓ Codegen service: LLM plain-language explanation + C99/Rust/Python codegen via SymPy — v6.0
- ✓ Orchestrator service (port 8775): HTTP trigger (POST /run) + configurable cron scheduling (APScheduler) — v7.0
- ✓ Docker Compose deployment: all 6 services, shared SQLite volume, health checks, startup ordering — v7.0

### Out of Scope

- CAS microservice migration — NOW standalone at /media/sam/1TB/cas-service/ (moved out of N8N_dev in v5.0)
- RAGAnything migration — already standalone systemd service at :8767, stays in N8N_dev
- N8N decommissioning — separate task after pipeline proven working
- Web UI/dashboard — Grafana handles visualization
- Message queue (Redis/RabbitMQ) — HTTP sync is sufficient for daily batch
- Cross-server deployment — all services run on Workstation (192.168.1.111)

## Context

**Current state (v7.0 SHIPPED — all milestones complete):**
- Shared library: 1,055 LOC Python across 5 modules (db.py, models.py, server.py, config.py, llm.py)
- Discovery service: 448 LOC (arXiv + S2 + CrossRef)
- Analyzer service: 600 LOC (LLM triple fallback + 5-criteria scoring)
- Extractor service: 644 LOC (PDF download + RAGAnything client + LaTeX regex engine)
- Validator service: 492 LOC (CAS client + fallback consensus + handler, engines: matlab/sympy/maxima)
- Codegen service: 567 LOC (SymPy C99/Rust/Python codegen + LLM explanation)
- CAS microservice: 698 LOC (standalone at /media/sam/1TB/cas-service/, SymPy + Maxima + MATLAB)
- SQLite schema: 5 tables, 6 indexes, WAL mode + prompt_version migration + validations table
- Orchestrator service: 850 LOC (pipeline dispatch, retry logic, cron scheduler)
- 9 Pydantic models with JSON field validators + FormulaExplanation validation-only model
- Base HTTP server with @route decorator, JSON logging, SIGTERM handling
- Dockerfile (multi-stage) + docker-compose.yml (6 services, network_mode:host)
- 463 non-e2e + 34 e2e = 497 total tests, 0 type errors
- Tech stack: Python stdlib (http.server, sqlite3, logging, json) + Pydantic + google-genai + requests + SymPy

**Origin**: N8N crashed in Jan 2026, external team restored 88 workflows but lost all data. The W1-W5 pipeline (17 N8N workflows) never successfully processed a paper end-to-end — all tables empty, 0 executions. Rather than fix N8N, rebuilding as standalone microservices eliminates the single point of failure.

**Existing services that continue working independently**:
- CAS Microservice (:8769) — NEW standalone repo /media/sam/1TB/cas-service/, 698 LOC, SymPy + Maxima + MATLAB (MATLAB license temp. unavailable)
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
- **Process mgmt**: Docker Compose (health checks, restart policies, startup ordering)
- **LLM**: Ollama qwen3:8b (local, free, already deployed)
- **Ports**: 8770-8775 (non-conflicting with existing services)
- **Dependencies**: External services are existing (CAS :8769, RAGAnything :8767, Ollama :11434)
- **KISS/YAGNI**: No abstractions beyond immediate needs. No message queues, no frameworks.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| http.server over FastAPI/Flask | Match CAS microservice pattern, zero extra deps, KISS | ✓ Good |
| Microservices over monolith | User chose for resilience + independent replaceability | — Pending |
| Docker Compose over systemd | User chose Docker for v7.0 — single `docker-compose up`, health checks, restart policies | — Pending |
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
| Separate LLM functions + fallback_chain | KISS, each ~30 LOC, easy to test/mock | — Pending |
| Simple mean scoring (5 equal-weight criteria) | Easy to debug, no arbitrary weights | — Pending |
| prompt_version column in papers table | Score comparability across prompt iterations | — Pending |
| Threshold 0.7 (restrittivo) | Filter ~60% non-relevant, save downstream resources | — Pending |
| REJECTED stage in PipelineStage | Distinguish deliberate filtering from errors (FAILED) | — Pending |
| `requests` + `urllib3.Retry` for PDF download | Already in deps, full retry/backoff control vs stdlib | ✓ Good |
| Sync polling for RAGAnything | KISS, no concurrent state management needed | ✓ Good |
| Stdlib `re` multi-pass for LaTeX | Zero deps, handles 95% of papers, occupied-span tracking | ✓ Good |
| Per-paper error isolation | One failure doesn't block batch, paper marked FAILED | ✓ Good |
| 200-char context window | Approximates N8N W3.2's "2-3 sentences" around formula | ✓ Good |
| New CAS microservice (standalone repo) | Old N8N_dev CAS was broken (SageMath), clean-room rewrite | ✓ Good |
| SymPy + Maxima + MATLAB engines | 3 engines for robust consensus; MATLAB license temp. unavailable | ✓ Good |
| All-or-nothing consensus | Both active engines must agree for VALID, disagreement → INVALID | ✓ Good |
| stdlib urllib.request for CAS client | No new deps in research-pipeline, consistent with KISS | ✓ Good |
| UNPARSEABLE stays 'extracted' | Don't promote formulas that no engine could parse | ✓ Good |
| Overwrite validations on re-run | DELETE+INSERT for same formula+engine, supports re-validation | ✓ Good |
| SymPy codegen() for C99/Rust | Reliable, maintained, proper type handling vs manual string formatting | ✓ Good |
| Ollama-first fallback for codegen | Local, free, faster for structured output; Gemini-first for analyzer | ✓ Good |
| parse_latex() ANTLR backend | More lenient than lark for real-world LaTeX | ✓ Good |
| Per-language error isolation | One codegen failure doesn't block other languages | ✓ Good |
| FormulaExplanation validation-only model | JSON stored in formulas.description, no separate table | ✓ Good |
| LLM client extraction to shared/llm.py | Reusable across analyzer + codegen, configurable fallback order | ✓ Good |

| APScheduler over host cron | Pure Python, travels with Docker stack, full env var access | — Pending |
| network_mode: host | External services (RAG:8767, CAS:8769, Ollama:11434) on host, simplest networking | — Pending |
| Shared SQLite volume | Sequential pipeline = no concurrent writers, WAL mode safe | — Pending |

| MATLAB first engine + fallback | MATLAB available, graceful degradation if down (>=2 agree → consensus) | — Pending |

---
*Last updated: 2026-02-14 after v7.0 milestone archived*
