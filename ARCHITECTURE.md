# PePeRS Architecture

> **Note**: Canonical architecture source. Auto-updated by architecture-validator.
> **Full documentation**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Overview

PePeRS (Paper Extraction, Processing, Evaluation, Retrieval & Synthesis) is a set of 5 standalone Python microservices plus 1 orchestrator that replaces the failed N8N W1-W5 academic paper processing pipeline. It discovers Kelly criterion papers from arXiv, enriches them with citation data, analyzes relevance with LLM providers (Gemini, OpenRouter, Ollama), extracts LaTeX formulas, validates formulas against multiple Computer Algebra Systems, and generates production Python/Rust code. All services share a common library (`shared/`) and communicate via HTTP JSON. The system is managed by systemd and monitored by an existing Prometheus + Grafana + Loki stack. All services share a single SQLite database with **schema v5**.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.11 | Core implementation (stdlib-first) |
| HTTP Server | `http.server` (stdlib) | Microservice endpoints (no framework) |
| Database | SQLite (WAL mode) | Shared data storage (`data/research.db`) |
| Models | Pydantic v2 | Data validation, serialization, type safety |
| LLM | Multi-provider (Gemini CLI/SDK, OpenRouter, Ollama, Claude CLI, Codex CLI) | Paper analysis, relevance scoring, codegen with fallback chain |
| CAS Engines | SymPy + SageMath (required); MATLAB + WolframAlpha (optional) | Multi-engine formula validation (consensus via CAS microservice) |
| PDF Processing | RAGAnything | Text extraction from paper PDFs |
| Secrets | dotenvx (ECIES) | Encrypted env var management |
| Process Mgmt | systemd | Service lifecycle, journald logging, watchdog |
| Monitoring | Prometheus + Grafana + Loki | Metrics, dashboards, centralized logs |
| Notifications | Apprise (90+ targets) | Pipeline completion summaries (Discord, Slack, Telegram, etc.) |

## Project Structure

```
pepers/
├── shared/                     # Shared library (all services import from here)
│   ├── __init__.py             # Package metadata (0.1.0)
│   ├── db.py                   # SQLite + WAL + migrations v5 (~340 LOC)
│   ├── models.py               # Pydantic v2 models (~320 LOC)
│   ├── server.py               # Base HTTP server + route dispatch (~400 LOC)
│   ├── config.py               # Config from RP_* env vars (~135 LOC)
│   ├── llm.py                  # LLM client: data-driven CLI registry + fallback chain (~420 LOC)
│   └── cli_providers.json      # CLI provider configs (claude_cli, codex_cli, gemini_cli)
├── services/                   # 6 microservice implementations + setup wizard
│   ├── setup/                  # Interactive wizard for config/install/health
│   ├── discovery/main.py       # arXiv + OpenAlex + S2 + CrossRef (495 LOC)
│   ├── discovery/openalex.py   # OpenAlex API client + upsert (195 LOC)
│   ├── analyzer/main.py        # LLM 5-criteria relevance scoring (321 LOC)
│   ├── extractor/main.py       # PDF -> LaTeX formula extraction via RAGAnything (265 LOC)
│   ├── validator/main.py       # Multi-CAS formula validation (339 LOC)
│   ├── codegen/                # Code generation
│   │   ├── main.py             # Service entry + endpoints (339 LOC)
│   │   ├── generators.py       # SymPy-based Python/Rust codegen (222 LOC)
│   │   └── explain.py          # LLM formula explanations + batch explain (206 LOC)
│   ├── orchestrator/           # Pipeline coordination
│   │   ├── main.py             # HTTP endpoints + async /run (534 LOC)
│   │   ├── pipeline.py         # Stage dispatch + retry + run persistence (533 LOC)
│   │   └── notifications.py    # Apprise multi-target notifications (68 LOC)
│   └── mcp/                    # MCP Server (SSE transport)
│       ├── server.py           # FastMCP server + 8 tools + arcade flavor (~260 LOC)
│       └── __main__.py         # Entry point: python -m services.mcp
├── tests/                      # 880+ tests
│   ├── conftest.py             # Shared fixtures
│   ├── unit/                   # 460+ unit tests
│   ├── integration/            # 185+ integration tests
│   ├── e2e/                    # 120+ E2E tests
│   └── smoke/                  # Smoke test templates (.j2)
├── scripts/                    # CLI tools
│   └── smoke_test.py           # E2E smoke test CLI (452 LOC)
├── deploy/                     # Deployment artifacts
│   ├── *.service               # 7 systemd service units (6 pipeline + MCP)
│   └── rp-pipeline.target      # systemd target for all services
├── data/                       # Runtime data (gitignored)
│   └── research.db             # SQLite database
├── docs/                       # Documentation
│   └── ARCHITECTURE.md         # Detailed architecture
├── .planning/                  # GSD planning artifacts
├── pyproject.toml              # Project metadata + dependencies
└── .python-version             # Python 3.11
```

## Core Components

### Component: Shared Library (`shared/`)

**Purpose**: Common infrastructure for all 6 microservices.
**Location**: `shared/`
**LOC**: ~1348 lines across 6 files

| Module | LOC | Purpose |
|--------|-----|---------|
| `db.py` | 333 | SQLite connection (WAL mode, FK ON), `transaction()` context manager, `init_db()`, schema migrations (v1-v5) |
| `models.py` | 306 | Pydantic v2 data models + `PipelineStage` enum, JSON field auto-parsing |
| `server.py` | 328 | `BaseHandler` + `BaseService` + `@route` decorator + `JsonFormatter` + `/health` endpoint |
| `config.py` | 131 | `Config` dataclass, `load_config()` from `RP_*` env vars |
| `llm.py` | 442 | Multi-provider LLM client (data-driven CLI registry, Gemini SDK, OpenRouter, Ollama), `fallback_chain()` orchestrator |
| `cli_providers.json` | 33 | Data-driven CLI provider configs (claude_cli, codex_cli, gemini_cli) |
| `__init__.py` | 10 | Package version (`0.1.0`) |

**Key interfaces**:

```python
# Database
from shared.db import get_connection, transaction, init_db

# Models
from shared.models import Paper, Formula, Validation, GeneratedCode, PipelineStage

# Server
from shared.server import BaseService, BaseHandler, route

# Config
from shared.config import load_config, Config

# LLM
from shared.llm import fallback_chain, call_gemini_cli, call_openrouter, call_ollama
```

### Component: Services

**Purpose**: Individual microservices that implement the paper processing pipeline.
**Location**: `services/`
**Status**: All 6 services implemented.

| Service | Port | LOC | Purpose | External Deps |
|---------|------|-----|---------|---------------|
| Discovery | 8770 | 495 | arXiv + OpenAlex + Semantic Scholar + CrossRef enrichment | arXiv, OpenAlex, S2, CrossRef APIs |
| Analyzer | 8771 | 321 | LLM analysis with 5-criteria relevance scoring | LLM (Gemini/OpenRouter/Ollama) |
| Extractor | 8772 | 265 | PDF text extraction + LaTeX formula extraction | RAGAnything (:8767) |
| Validator | 8773 | 339 | Multi-CAS formula validation with consensus | CAS (:8769), SymPy |
| Codegen | 8774 | 339+311 | Python (SymPy) + Rust code gen + batch LLM explanations | LLM (Ollama/Gemini) |
| Orchestrator | 8775 | 534+533 | Async pipeline runs, GET /generated-code, GET /runs, semantic search, retry, batch | All above + RAGAnything query + Apprise notifications |
| MCP Server | 8776 | ~260 | MCP SSE interface — 8 tools wrapping orchestrator API for Claude Desktop/Cursor | MCP SDK, Orchestrator (:8775) |

### Component: LLM Providers (`shared/llm.py` + `shared/cli_providers.json`)

**Purpose**: Multi-provider LLM abstraction with automatic failover.
**Location**: `shared/llm.py`, `shared/cli_providers.json`

The pipeline uses `fallback_chain()` which tries providers in order until one succeeds:

| Provider | Method | Temperature | Seed | Timeout Default |
|----------|--------|-------------|------|-----------------|
| Claude CLI | subprocess (`claude --print`) via data-driven registry | Not supported | Not supported | 120s |
| Codex CLI | subprocess (`codex exec`) via data-driven registry | Not supported | Not supported | 120s |
| Gemini CLI | subprocess (`gemini -p`) via data-driven registry | Not supported | Not supported | 120s |
| Gemini SDK | Python SDK (`google-genai`) | Configurable (default: 0) | Configurable (default: 42) | 60s |
| OpenRouter | OpenAI-compatible API | Configurable (default: 0) | Configurable (default: 42) | 60s |
| Ollama | Local LLM (qwen3:8b default) | Configurable (default: 0) | Configurable (default: 42) | 600s |

**Default fallback order**: `gemini_cli -> codex_cli -> claude_cli -> openrouter -> ollama` (configurable via `RP_LLM_FALLBACK_ORDER`)
**Codegen fallback order**: same as default (configurable via `RP_CODEGEN_FALLBACK_ORDER`, falls back to `RP_LLM_FALLBACK_ORDER`)

CLI providers are **data-driven**: `shared/cli_providers.json` defines command, flags, input mode, and timeout for each CLI tool. Adding a new CLI provider requires only a JSON entry, no Python changes. The generic `call_cli(provider_name, prompt)` function reads the config and executes the correct subprocess.

All providers default to `temperature=0` and `seed=42` for deterministic output (except CLI providers which do not support these parameters).

### Component: Batch Explain (`services/codegen/explain.py`)

**Purpose**: Reduce LLM calls for formula explanations by batching.
**Location**: `services/codegen/explain.py`

Instead of 1 LLM call per formula (N calls for N formulas), `explain_formulas_batch()` groups formulas into chunks of `RP_CODEGEN_BATCH_SIZE` (default: 50) and sends one call per chunk. For 100 formulas, this reduces from 100 calls to 2 calls.

Falls back to per-formula `explain_formula()` for any formulas that fail batch processing.

### Component: Test Suite (`tests/`)

**Purpose**: Validates all shared library and service correctness.
**Location**: `tests/`
**Results**: 700+ tests pass (668 non-e2e + 60+ e2e)

| Category | Tests | What it covers |
|----------|-------|----------------|
| Unit | 460+ | All shared/ modules + all services in isolation |
| Integration | 185+ | DB round-trips, HTTP + DB, resilience, hardening |
| E2E | 60+ | Full pipeline flows, async /run, GET endpoints, real APIs |
| Smoke (templates) | -- | Jinja2 templates (.j2) for deployment validation |

## Data Flow

```
Daily 8AM timer triggers Orchestrator (:8775)
         |
         v
  Discovery (:8770)
  +-- Query arXiv API (keywords: kelly criterion, portfolio optimization, ...)
  +-- Query OpenAlex API (200M+ works, configurable via RP_DISCOVERY_SOURCES)
  +-- Cross-source dedup (same paper from arXiv + OpenAlex merged)
  +-- Enrich via Semantic Scholar (citations, references, tldr)
  +-- Enrich via CrossRef (DOI metadata)
  +-- INSERT papers -> SQLite [stage=discovered]
         |
         v
  Analyzer (:8771)
  +-- Send to LLM via fallback_chain (gemini_cli -> openrouter -> ollama)
  +-- 5-criteria relevance scoring (0-10 each)
  +-- UPDATE papers [stage=analyzed, score=N]
         |
         v
  Extractor (:8772)
  +-- Send PDF to RAGAnything (:8767)
  +-- LaTeX formula extraction
  +-- INSERT formulas -> SQLite [stage=extracted]
         |
         v
  Validator (:8773)
  +-- Validate with SymPy + SageMath via CAS (:8769); optional MATLAB, WolframAlpha
  +-- Consensus scoring (2/3 agree = valid)
  +-- UPDATE formulas [stage=validated]
         |
         v
  Codegen (:8774)
  +-- Python codegen via SymPy symbolic -> numeric
  +-- Rust codegen via AST-based transpilation
  +-- LLM explanations via fallback_chain (ollama -> openrouter -> gemini_cli)
  +-- INSERT generated_code -> SQLite [stage=codegen]
         |
         v
  Orchestrator: mark [stage=complete], send Apprise notification
```

## Database Schema

8 tables with foreign key relationships (schema version: v5):

| Table | Purpose | Populated By |
|-------|---------|-------------|
| `papers` | Academic paper metadata (arXiv/OpenAlex + enrichment, source tracking) | Discovery |
| `formulas` | Extracted LaTeX formulas with SHA-256 hash, UNIQUE(paper_id, latex_hash) | Extractor |
| `validations` | CAS validation results per formula per engine | Validator |
| `generated_code` | Generated Python/Rust code per formula | Codegen |
| `pipeline_runs` | Async pipeline execution tracking (run_id, status, params, results) | Orchestrator |
| `schema_version` | Migration tracking (current: v5) | init_db() |
| `github_repos` | GitHub repository metadata from code search | GitHub Discovery |
| `github_analyses` | Gemini analysis results for GitHub repos | GitHub Discovery |

## Key Technical Decisions

| # | Decision | Rationale | Trade-offs |
|---|----------|-----------|------------|
| 1 | SQLite over PostgreSQL | ~10 papers/day, zero infra, WAL for concurrent reads | No multi-server deployment |
| 2 | http.server over FastAPI | Match CAS pattern, zero deps, KISS | No async, no OpenAPI |
| 3 | Microservices over monolith | Independent restart/replace, one failure != total failure | More systemd units |
| 4 | Monorepo with shared/ | Single venv, simple imports, easy cross-service refactor | No independent versioning |
| 5 | @route decorator dispatch | Clean endpoint separation in 14 lines | Attribute introspection |
| 6 | JSON structured logging | Direct Loki/journald integration, Grafana queryable | Less human-readable |
| 7 | Full independence from N8N | Clean break after N8N crash/data loss | Must reimplement coordination |
| 8 | Multi-provider LLM fallback | Resilience against single provider outages | Complex config, non-deterministic Gemini CLI |
| 9 | Schema migrations (v1->v5) | Safe DB evolution with UNIQUE constraints + run tracking + multi-source | Migration complexity |
| 10 | systemd + watchdog | Auto-restart crashed services, health monitoring | Linux-only deployment |

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `RP_{SERVICE}_PORT` | TCP port for a service | See port map |
| `RP_DB_PATH` | Path to SQLite database | `./data/research.db` |
| `RP_DISCOVERY_SOURCES` | Comma-separated discovery sources | `arxiv` (options: `arxiv,openalex`) |
| `RP_LOG_LEVEL` | Logging level | `INFO` |
| `RP_DATA_DIR` | Directory for data files | `./data/` |
| `RP_LLM_TEMPERATURE` | LLM sampling temperature | `0` (deterministic) |
| `RP_LLM_FALLBACK_ORDER` | LLM provider fallback order | `gemini_cli,codex_cli,claude_cli,openrouter,ollama` |
| `RP_CODEGEN_FALLBACK_ORDER` | Codegen-specific fallback (overrides above) | same as `RP_LLM_FALLBACK_ORDER` |
| `RP_LLM_TIMEOUT_CLAUDE_CLI` | Claude CLI timeout | `120s` |
| `RP_LLM_TIMEOUT_CODEX_CLI` | Codex CLI timeout | `120s` |
| `RP_LLM_TIMEOUT_GEMINI_CLI` | Gemini CLI timeout | `120s` |
| `RP_LLM_TIMEOUT_GEMINI_SDK` | Gemini SDK timeout | `60s` |
| `RP_LLM_TIMEOUT_OPENROUTER` | OpenRouter timeout | `60s` |
| `RP_LLM_TIMEOUT_OLLAMA` | Ollama timeout | `600s` |
| `RP_CODEGEN_BATCH_SIZE` | Formulas per batch explain call | `50` |
| `RP_ORCHESTRATOR_TIMEOUT` | Orchestrator per-service timeout | `300s` |
| `RP_NOTIFY_URLS` | Apprise notification URLs (comma-separated) | `` (disabled) |
| `RP_RAG_QUERY_URL` | RAGAnything query endpoint | `http://localhost:8767` |
| `RP_RAG_QUERY_TIMEOUT` | RAG query timeout (seconds) | `30` |

## Infrastructure

- **Host**: Workstation (192.168.1.111), Ubuntu
- **Process management**: systemd services (6 units + 1 target in `deploy/`)
- **Service reliability**: `Restart=always`, `RestartSec=5` on all services
- **Health checks**: `/health` endpoint on all services (DB check, schema version, uptime)
- **Startup validation**: Consistency checks on extractor, validator, codegen at boot
- **Daily trigger**: systemd timer at 8:00 AM activating the Orchestrator
- **Monitoring**: Prometheus + Grafana dashboard + Loki structured logs
- **Alerts**: Apprise multi-target notifications (`RP_NOTIFY_URLS`)
- **External services**: CAS (:8769), RAGAnything (:8767), Ollama (:11434)

## Development Status

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.0 Foundation | 1-4 | Complete | 2026-02-10 |
| v2.0 Discovery | 5-7 | Complete | 2026-02-12 |
| v3.0 Analyzer | 8-10 | Complete | 2026-02-13 |
| v4.0 Extractor | 11-13 | Complete | 2026-02-13 |
| v5.0 Validator | 14-16 | Complete | 2026-02-14 |
| v6.0 Codegen | 17-19 | Complete | 2026-02-14 |
| v7.0 Orchestrator+Deploy | 20-22 | Complete | 2026-02-14 |
| v8.0 GitHub Discovery | 25-27 | Complete | 2026-02-15 |
| v9.0 Pipeline Hardening | 28-30 | Complete | 2026-02-16 |
| v10.0 Production Hardening | 32-34 | Complete | 2026-02-17 |
| v11.0 CLI Providers+API+Async | 35-37 | Complete | 2026-02-18 |

## Related Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- Full detailed architecture (API contracts, design rationale, agent integration)
- [README.md](README.md) -- Quick start and usage guide

---

*Architecture documented: 2026-02-25*
*Last validated: 2026-02-25 (880+ tests pass, schema v5)*
*Auto-updated by architecture-validator agent*
