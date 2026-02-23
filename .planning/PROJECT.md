# PePeRS (Paper Extraction, Processing, Evaluation, Retrieval & Synthesis)

## What This Is

PePeRS — a set of 6 standalone Python microservices + 1 orchestrator + 1 MCP server that replaces the N8N W1-W5 research paper pipeline. Discovers academic papers from arXiv and OpenAlex (200M+ works), enriches with citation data, analyzes with LLM, extracts formulas, validates with multi-CAS consensus, and generates Python/Rust code. Exposed via MCP Server SSE (8 tools) for Claude Desktop/Cursor integration. Deployed via Docker Compose or `uv tool install pepers`.

## Core Value

Reliable, N8N-free academic paper processing pipeline that discovers papers from arXiv + OpenAlex, validates mathematical formulas with multiple CAS engines, generates production code, and exposes everything via MCP tools — all as independent, replaceable microservices.

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

<!-- No active milestone — next milestone TBD -->

(None — all v13.0 requirements shipped. Define next milestone with `/gsd:new-milestone`.)

### Validated (v1.0-v13.0)

- ✓ Shared library: DB connection pool, Pydantic models, base HTTP server, config management — v1.0
- ✓ Each service exposes /health, /status, /process endpoints — v1.0
- ✓ dotenvx secret management aligned with SSOT at /media/sam/1TB/.env — v1.0
- ✓ Discovery service: arXiv + Semantic Scholar/CrossRef enrichment — v2.0
- ✓ Analyzer service: LLM triple fallback + 5-criteria relevance scoring — v3.0
- ✓ Extractor service: PDF download + RAGAnything + 5-pass LaTeX regex — v4.0
- ✓ Validator service: multi-CAS validation (SymPy + Maxima + MATLAB) with consensus — v5.0
- ✓ Codegen service: LLM explanation + C99/Rust/Python codegen via SymPy — v6.0
- ✓ Orchestrator: HTTP trigger + cron scheduling + async /run — v7.0
- ✓ Docker Compose deployment: all services, health checks, startup ordering — v7.0
- ✓ GitHub Discovery: search repos + Gemini CLI analysis — v8.0
- ✓ Pipeline hardening: stage transitions, batch overflow, LaTeX filtering — v9.0
- ✓ Production hardening: systemd units, schema migrations, /health enhanced, LLM determinism — v10.0
- ✓ CLI providers: data-driven registry, batch explain, async /run, GET /generated-code — v11.0
- ✓ PePeRS branding: naming, logo, professional README — v12.0
- ✓ RAGAnything context_only mode (<2s response) — v12.0
- ✓ MCP Server SSE: 8 tools on :8776 with arcade flavor — v12.0
- ✓ One-click install: Docker compose + uv tool install + pepers-mcp CLI — v12.0
- ✓ OpenAlex multi-source discovery: 200M+ works, schema v5, cross-source dedup — v12.0
- ✓ ThreadingHTTPServer + 10MB body limit + SQLite thread safety on all services — v13.0
- ✓ Stuck pipeline run cleanup at orchestrator startup — v13.0
- ✓ Prometheus /metrics on all services (request counters, histograms, error counts, pipeline metrics) — v13.0
- ✓ Docker production hardening: log rotation, memory limits, init:true, graceful shutdown — v13.0
- ✓ Monitoring integration: process-exporter, VictoriaMetrics scrape, Grafana dashboard (6 panels), alert rules — v13.0

### Out of Scope

- CAS microservice migration — NOW standalone at /media/sam/1TB/cas-service/ (moved out of N8N_dev in v5.0)
- RAGAnything migration — already standalone systemd service at :8767, stays in N8N_dev
- N8N decommissioning — separate task after pipeline proven working
- Web UI/dashboard — Grafana handles visualization
- Message queue (Redis/RabbitMQ) — HTTP sync is sufficient for daily batch
- Cross-server deployment — all services run on Workstation (192.168.1.111)

## Context

**Current state (v13.0 SHIPPED — 13 milestones complete, 46 phases):**
- Shared library: ~1,300 LOC Python (db.py, models.py, server.py, config.py, llm.py, metrics.py, cli_providers.json)
- Discovery service: ~560 LOC (arXiv + OpenAlex + S2 + CrossRef, adapter pattern)
- Analyzer service: ~600 LOC (LLM triple fallback + 5-criteria scoring)
- Extractor service: ~644 LOC (PDF download + RAGAnything + 5-pass LaTeX regex)
- Validator service: ~492 LOC (CAS client + fallback consensus + stage update)
- Codegen service: ~650 LOC (SymPy codegen + batch explain + clean_latex)
- GitHub Discovery: ~621 LOC (GitHub API + Gemini CLI/SDK analysis)
- Orchestrator service: ~1,000 LOC (pipeline dispatch, async /run, batch iteration, notifications, pipeline metrics)
- MCP Server: ~427 LOC (8 SSE tools, arcade flavor, pepers-mcp CLI)
- CAS microservice: 698 LOC (standalone at /media/sam/1TB/cas-service/)
- SQLite schema v5: 8 tables (papers, formulas, validations, generated_code, github_repos, github_analyses, pipeline_runs, schema_version)
- 828 tests (all passing)
- ~15,500 LOC Python total
- Tech stack: Python stdlib + Pydantic + google-genai + requests + SymPy + mcp SDK + apprise + prometheus-client
- Distribution: Docker Compose + uv tool install + pepers-mcp CLI
- Monitoring: VictoriaMetrics scrape (6 targets), Grafana dashboard (6 panels), alert rules (service-down + no-papers)

**Origin**: N8N crashed in Jan 2026, external team restored 88 workflows but lost all data. The W1-W5 pipeline (17 N8N workflows) never successfully processed a paper end-to-end — all tables empty, 0 executions. Rather than fix N8N, rebuilding as standalone microservices eliminates the single point of failure.

**Existing services that continue working independently**:
- CAS Microservice (:8769) — NEW standalone repo /media/sam/1TB/cas-service/, 698 LOC, SymPy + Maxima + MATLAB (MATLAB license temp. unavailable)
- RAGAnything (:8767) — systemd system service, 1,100 LOC, 743MB RAM, LightRAG + OpenAI/Ollama
- Ollama — local LLM (qwen3:8b) on localhost:11434
- PostgreSQL — N8N's postgres container (n8n-postgres-1), tables in public schema

**Monitoring stack** (`/media/sam/1TB/monitoring-stack/`):
- VictoriaMetrics (:8428) + node_exporter + process-exporter + alertmanager
- Grafana (:3000) with dashboards (System, Hyperliquid, PePeRS Pipeline) + provisioned alert rules
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
| ThreadingHTTPServer over async | stdlib, zero deps, matches existing pattern, sufficient for ~10 papers/day | ✓ Good |
| prometheus-client library | Only new dependency (~60KB), standard Prometheus text format | ✓ Good |
| shared/server.py as single change point | Threading + body limits + metrics middleware in one place | ✓ Good |
| YAML extension fields for Docker config | x-logging, x-deploy-* for DRY compose config | ✓ Good |
| init:true on all containers | Proper signal forwarding, zombie process reaping | ✓ Good |
| honor_labels:true in scrape config | Preserve PePeRS' own service label vs scrape job label | ✓ Good |
| Grafana provisioned alerting over Prometheus rules | VictoriaMetrics has no vmalert component, Grafana evaluates rules | ✓ Good |

---
*Last updated: 2026-02-23 after v13.0 milestone shipped*
