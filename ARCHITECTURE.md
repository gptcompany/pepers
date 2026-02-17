# Research Pipeline Architecture

> **Note**: Canonical architecture source. Auto-updated by architecture-validator.
> **Full documentation**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Overview

Research Pipeline is a set of 5 standalone Python microservices plus 1 orchestrator that replaces the failed N8N W1-W5 academic paper processing pipeline. It discovers Kelly criterion papers from arXiv, enriches them with citation data, analyzes relevance with LLM providers (Gemini, OpenRouter, Ollama), extracts LaTeX formulas, validates formulas against multiple Computer Algebra Systems, and generates production Python/Rust code. All services share a common library (`shared/`) and communicate via HTTP JSON. The system is managed by systemd and monitored by an existing Prometheus + Grafana + Loki stack.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.11 | Core implementation (stdlib-first) |
| HTTP Server | `http.server` (stdlib) | Microservice endpoints (no framework) |
| Database | SQLite (WAL mode) | Shared data storage (`data/research.db`) |
| Models | Pydantic v2 | Data validation, serialization, type safety |
| LLM | Multi-provider (Gemini CLI/SDK, OpenRouter, Ollama) | Paper analysis, relevance scoring, codegen with fallback chain |
| CAS Engines | SymPy + Maxima + Wolfram | Multi-engine formula validation (consensus) |
| PDF Processing | RAGAnything | Text extraction from paper PDFs |
| Secrets | dotenvx (ECIES) | Encrypted env var management |
| Process Mgmt | systemd | Service lifecycle, journald logging, watchdog |
| Monitoring | Prometheus + Grafana + Loki | Metrics, dashboards, centralized logs |
| Notifications | Discord webhook | Pipeline completion summaries |

## Project Structure

```
research-pipeline/
├── shared/                     # Shared library (all services import from here)
│   ├── __init__.py             # Package metadata (0.1.0)
│   ├── db.py                   # SQLite + WAL + migrations (261 LOC)
│   ├── models.py               # Pydantic v2 models (306 LOC)
│   ├── server.py               # Base HTTP server + route dispatch (328 LOC)
│   ├── config.py               # Config from RP_* env vars (131 LOC)
│   └── llm.py                  # LLM client: Gemini CLI/SDK, OpenRouter, Ollama + fallback chain (312 LOC)
├── services/                   # 6 microservice implementations
│   ├── discovery/main.py       # arXiv + Semantic Scholar + CrossRef (448 LOC)
│   ├── analyzer/main.py        # LLM 5-criteria relevance scoring (321 LOC)
│   ├── extractor/main.py       # PDF -> LaTeX formula extraction via RAGAnything (265 LOC)
│   ├── validator/main.py       # Multi-CAS formula validation (339 LOC)
│   ├── codegen/                # Code generation
│   │   ├── main.py             # Service entry + endpoints (339 LOC)
│   │   ├── generators.py       # SymPy-based Python/Rust codegen (222 LOC)
│   │   └── explain.py          # LLM formula explanations (89 LOC)
│   └── orchestrator/main.py    # Pipeline coordination + retry + Discord (437 LOC)
├── tests/                      # 671+ tests
│   ├── conftest.py             # Shared fixtures
│   ├── unit/                   # 445 unit tests
│   ├── integration/            # 169 integration tests
│   ├── e2e/                    # 54 E2E tests
│   └── smoke/                  # Smoke test templates (.j2)
├── scripts/                    # CLI tools
│   └── smoke_test.py           # E2E smoke test CLI (452 LOC)
├── deploy/                     # Deployment artifacts
│   ├── *.service               # 6 systemd service units
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
| `db.py` | 261 | SQLite connection (WAL mode, FK ON), `transaction()` context manager, `init_db()`, schema migrations (v1-v3) |
| `models.py` | 306 | Pydantic v2 data models + `PipelineStage` enum, JSON field auto-parsing |
| `server.py` | 328 | `BaseHandler` + `BaseService` + `@route` decorator + `JsonFormatter` + `/health` endpoint |
| `config.py` | 131 | `Config` dataclass, `load_config()` from `RP_*` env vars |
| `llm.py` | 312 | Multi-provider LLM client (Gemini CLI/SDK, OpenRouter, Ollama), `fallback_chain()` orchestrator |
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
| Discovery | 8770 | 448 | arXiv API + Semantic Scholar + CrossRef enrichment | arXiv, S2, CrossRef APIs |
| Analyzer | 8771 | 321 | LLM analysis with 5-criteria relevance scoring | LLM (Gemini/OpenRouter/Ollama) |
| Extractor | 8772 | 265 | PDF text extraction + LaTeX formula extraction | RAGAnything (:8767) |
| Validator | 8773 | 339 | Multi-CAS formula validation with consensus | CAS (:8769), SymPy |
| Codegen | 8774 | 339+311 | Python (SymPy) + Rust code gen + LLM explanations | LLM (Ollama/Gemini) |
| Orchestrator | 8775 | 437 | Pipeline coordination, retry, batch, Discord alerts | All above + Discord webhook |

### Component: LLM Providers (`shared/llm.py`)

**Purpose**: Multi-provider LLM abstraction with automatic failover.
**Location**: `shared/llm.py`

The pipeline uses `fallback_chain()` which tries providers in order until one succeeds:

| Provider | Method | Temperature | Seed | Timeout Default |
|----------|--------|-------------|------|-----------------|
| Gemini CLI | subprocess call | Not supported (CLI limitation) | Not supported | 120s |
| Gemini SDK | Python SDK (`google-genai`) | Configurable (default: 0) | Configurable (default: 42) | 60s |
| OpenRouter | OpenAI-compatible API | Configurable (default: 0) | Configurable (default: 42) | 60s |
| Ollama | Local LLM (qwen3:8b default) | Configurable (default: 0) | Configurable (default: 42) | 600s |

**Default fallback order**: gemini_cli -> openrouter -> ollama
**Codegen fallback order**: ollama -> openrouter -> gemini_cli

All providers default to `temperature=0` and `seed=42` for deterministic output (except Gemini CLI which does not support these parameters).

### Component: Test Suite (`tests/`)

**Purpose**: Validates all shared library and service correctness.
**Location**: `tests/`
**Results**: 671+ tests pass

| Category | Tests | What it covers |
|----------|-------|----------------|
| Unit | 445 | All shared/ modules + all services in isolation |
| Integration | 169 | DB round-trips, HTTP + DB, resilience, hardening |
| E2E | 54 | Full pipeline flows with real APIs, smoke tests |
| Smoke (templates) | -- | Jinja2 templates (.j2) for deployment validation |

## Data Flow

```
Daily 8AM timer triggers Orchestrator (:8775)
         |
         v
  Discovery (:8770)
  +-- Query arXiv API (keywords: kelly criterion, portfolio optimization, ...)
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
  +-- Validate with SymPy, Maxima (CAS :8769), Wolfram Alpha
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
  Orchestrator: mark [stage=complete], send Discord summary
```

## Database Schema

7 tables with foreign key relationships (schema version: v3):

| Table | Purpose | Populated By |
|-------|---------|-------------|
| `papers` | Academic paper metadata (arXiv + enrichment) | Discovery |
| `formulas` | Extracted LaTeX formulas with SHA-256 hash, UNIQUE(paper_id, latex_hash) | Extractor |
| `validations` | CAS validation results per formula per engine | Validator |
| `generated_code` | Generated Python/Rust code per formula | Codegen |
| `schema_version` | Migration tracking (current: v3) | init_db() |
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
| 9 | Schema migrations (v1->v3) | Safe DB evolution with UNIQUE constraints | Migration complexity |
| 10 | systemd + watchdog | Auto-restart crashed services, health monitoring | Linux-only deployment |

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `RP_{SERVICE}_PORT` | TCP port for a service | See port map |
| `RP_DB_PATH` | Path to SQLite database | `./data/research.db` |
| `RP_LOG_LEVEL` | Logging level | `INFO` |
| `RP_DATA_DIR` | Directory for data files | `./data/` |
| `RP_LLM_TEMPERATURE` | LLM sampling temperature | `0` (deterministic) |
| `RP_LLM_TIMEOUT_GEMINI_CLI` | Gemini CLI timeout | `120s` |
| `RP_LLM_TIMEOUT_GEMINI_SDK` | Gemini SDK timeout | `60s` |
| `RP_LLM_TIMEOUT_OPENROUTER` | OpenRouter timeout | `60s` |
| `RP_LLM_TIMEOUT_OLLAMA` | Ollama timeout | `600s` |
| `RP_ORCHESTRATOR_TIMEOUT` | Orchestrator per-service timeout | `300s` |

## Infrastructure

- **Host**: Workstation (192.168.1.111), Ubuntu
- **Process management**: systemd services (6 units + 1 target in `deploy/`)
- **Service reliability**: `Restart=always`, `RestartSec=5` on all services
- **Health checks**: `/health` endpoint on all services (DB check, schema version, uptime)
- **Startup validation**: Consistency checks on extractor, validator, codegen at boot
- **Daily trigger**: systemd timer at 8:00 AM activating the Orchestrator
- **Monitoring**: Prometheus + Grafana dashboard + Loki structured logs
- **Alerts**: Discord webhook for pipeline completion/failure summaries
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
| v10.0 Production Hardening | 32-34 | In Progress | -- |

## Related Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- Full detailed architecture (API contracts, design rationale, agent integration)
- [README.md](README.md) -- Quick start and usage guide

---

*Architecture documented: 2026-02-10*
*Last validated: 2026-02-17 (671+ tests pass)*
*Auto-updated by architecture-validator agent*
