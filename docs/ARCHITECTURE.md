# Research Pipeline Architecture

> **Note**: Canonical architecture source. Auto-updated by architecture-validator.

## Overview

Research Pipeline is a set of 5 standalone Python microservices plus 1 orchestrator that replaces the failed N8N W1-W5 academic paper processing pipeline. It discovers Kelly criterion papers from arXiv, enriches them with citation data, analyzes relevance with a local LLM, extracts LaTeX formulas, validates formulas against multiple Computer Algebra Systems, and generates production Python/Rust code. All services share a common library (`shared/`) and communicate via HTTP JSON. The system is managed by systemd and monitored by an existing Prometheus + Grafana + Loki stack.

The project originated after N8N crashed in January 2026 and the restored 17 workflows had never successfully processed a single paper end-to-end (all tables empty, 0 executions). Rather than fix N8N, the pipeline is being rebuilt as independent, replaceable microservices.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | Python 3.11 | Core implementation (stdlib-first) |
| HTTP Server | `http.server` (stdlib) | Microservice endpoints (no framework) |
| Database | SQLite (WAL mode) | Shared data storage (`data/research.db`) |
| Models | Pydantic v2 | Data validation, serialization, type safety |
| LLM | Fallback chain (gemini_cli → codex_cli → claude_cli → openrouter → ollama) | Paper analysis, relevance scoring, codegen explanations |
| CAS Engines | SymPy + Maxima + Wolfram | Multi-engine formula validation (consensus) |
| PDF Processing | RAGAnything | Text extraction from paper PDFs |
| Secrets | dotenvx (ECIES) | Encrypted env var management |
| Process Mgmt | systemd | Service lifecycle, journald logging |
| Monitoring | Prometheus + Grafana + Loki | Metrics, dashboards, centralized logs |
| Notifications | Discord webhook | Pipeline completion summaries |

## Project Structure

```
research-pipeline/
├── shared/                     # Shared library (all services import from here)
│   ├── __init__.py             # Package metadata, convenience imports
│   ├── db.py                   # SQLite connection management (WAL mode)
│   ├── models.py               # Pydantic v2 data models (8 models + enum)
│   ├── server.py               # Base HTTP server + route dispatch + JSON helpers
│   └── config.py               # Config loading from RP_* env vars + dotenvx
├── services/                   # Microservice implementations (one dir per service)
│   └── .gitkeep                # Placeholder (services built in future milestones)
├── tests/                      # Test suite (685+ tests, unit/integration/e2e)
│   ├── conftest.py             # Shared fixtures (memory_db, tmp_db_path, sample data)
│   ├── unit/                   # Unit tests (fast, no I/O)
│   │   ├── test_db.py          # 16 tests: get_connection, transaction, init_db
│   │   ├── test_models.py      # 30 tests: all 8 Pydantic models + JSON parsers
│   │   ├── test_config.py      # 12 tests: Config dataclass, load_config, env vars
│   │   └── test_server.py      # 19 tests: JsonFormatter, route, BaseHandler, BaseService
│   ├── integration/            # Integration tests (DB + HTTP)
│   │   ├── test_db_models.py   # 7 tests: model <-> SQLite round-trip, full pipeline flow
│   │   └── test_server_http.py # 3 tests: HTTP server with real SQLite operations
│   └── smoke/                  # Smoke test templates (Jinja2 .j2 files, for services)
│       ├── conftest.py.j2
│       ├── test_api_endpoints.py.j2
│       ├── test_config.py.j2
│       ├── test_connectivity.py.j2
│       ├── test_data_integrity.py.j2
│       └── test_imports.py.j2
├── data/                       # Runtime data (gitignored)
│   └── research.db             # SQLite database
├── .planning/                  # GSD planning artifacts
│   ├── PROJECT.md              # Project definition and requirements
│   ├── ROADMAP.md              # Phase roadmap and progress
│   ├── STATE.md                # Current state and accumulated context
│   ├── config.json             # GSD workflow configuration
│   └── phases/                 # Per-phase context, plans, summaries
├── pyproject.toml              # Project metadata + dependencies
├── .python-version             # Python 3.11
└── .env                        # dotenvx encrypted secrets (not committed)
```

## Core Components

### Component: Shared Library (`shared/`)

**Purpose**: Common infrastructure for all 6 microservices. Eliminates duplication and enforces consistent patterns across the pipeline.
**Location**: `/media/sam/1TB/research-pipeline/shared/`
**LOC**: 816 lines across 5 files

#### `shared/db.py` -- SQLite Database Layer (170 LOC)

**Purpose**: Connection management and schema initialization for the shared SQLite database.

**Key functions**:
- `get_connection(db_path)` -- Creates a connection with WAL mode, foreign keys ON, and Row factory
- `transaction(db_path)` -- Context manager with auto-commit on success, rollback on exception
- `init_db(db_path)` -- Idempotent schema creation (5 tables, 6 indexes)

**Schema** (5 tables):

| Table | Purpose | Populated By |
|-------|---------|-------------|
| `papers` | Academic paper metadata (arXiv + enrichment) | Discovery service |
| `formulas` | Extracted LaTeX formulas with SHA-256 hash | Extractor service |
| `validations` | CAS validation results per formula per engine | Validator service |
| `generated_code` | Generated Python/Rust code per formula | Codegen service |
| `schema_version` | Migration tracking (current: v1) | init_db() |

**Design decisions**:
- WAL mode enables concurrent reads (orchestrator reads while a service writes)
- Foreign keys enforced at connection level via PRAGMA
- `sqlite3.Row` factory for dict-like column access
- Single connection per request (no pool -- daily batch of ~10 papers)
- Schema as SQL string constant (no migration framework -- YAGNI)

#### `shared/models.py` -- Pydantic Data Models (222 LOC)

**Purpose**: Type-safe data transfer between services and database with validation and serialization.

**Models**:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `Paper` | Academic paper metadata | arxiv_id, title, abstract, authors, citation_count, stage |
| `Formula` | Extracted LaTeX formula | paper_id, latex, latex_hash (auto SHA-256), formula_type |
| `Validation` | CAS validation result | formula_id, engine, is_valid, result, time_ms |
| `GeneratedCode` | Generated code output | formula_id, language, code, metadata |
| `LLMCodegenResult` | LLM fallback codegen response | python_code, variables, description |
| `ServiceStatus` | /health and /status response | status, service, version, uptime_seconds |
| `ProcessRequest` | Base /process request | paper_id, formula_id, force |
| `ProcessResponse` | Base /process response | success, service, time_ms, error |
| `ErrorResponse` | Standard error format | error, code, details |

**Enum**: `PipelineStage` -- discovered, analyzed, extracted, validated, codegen, complete, failed

**Serialization strategy**:
- JSON list/dict fields stored as TEXT in SQLite, auto-parsed by `field_validator`
- `Formula.latex_hash` auto-computed via `model_validator` (SHA-256 of raw LaTeX)
- All datetime fields stored as ISO 8601 strings

#### `shared/server.py` -- Base HTTP Server (297 LOC)

**Purpose**: Reusable HTTP server with JSON handling, decorator-based routing, and standard endpoints.

**Key classes**:
- `BaseHandler` -- Request handler with route dispatch, `send_json()`, `read_json()`, `send_error_json()`
- `BaseService` -- Server wrapper with SIGTERM handling, JSON structured logging, and auto-registered endpoints
- `JsonFormatter` -- Structured JSON log output for Loki/journald integration
- `route(method, path)` -- Decorator to register handler methods

**Auto-registered endpoints**:
- `GET /health` -- `{"status": "ok", "service": "name", "uptime_seconds": N}`
- `GET /status` -- Extended info (version, db_path, etc.)

**Usage pattern**:
```python
from shared.server import BaseService, BaseHandler, route

class MyHandler(BaseHandler):
    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        return {"result": "processed"}

service = BaseService("my-service", port=8770, handler=MyHandler)
service.run()
```

**Improvements over the CAS microservice reference pattern**:

| CAS Pattern | Shared Lib Improvement |
|-------------|----------------------|
| Monolithic do_POST/do_GET | `@route("POST", "/path")` decorator dispatch |
| Manual JSON encode/decode | `send_json()`, `read_json()` helpers |
| Bare 500 for all errors | Typed errors: 400, 404, 422, 500 with error codes |
| Logging suppressed | Python `logging` module, JSON structured for Loki |
| KeyboardInterrupt only | SIGTERM handler for clean systemd stop |
| No /status endpoint | /health + /status auto-registered |

#### `shared/config.py` -- Configuration Management (117 LOC)

**Purpose**: Load service configuration from environment variables with sensible defaults.

**Key interface**:
- `load_config(service_name)` -- Returns a populated `Config` dataclass
- `Config` dataclass -- Fields: service_name, port, db_path, log_level, data_dir

**Env var naming convention**: `RP_{SERVICE}_{FIELD}`
```
RP_DISCOVERY_PORT=8770
RP_ANALYZER_PORT=8771
RP_DB_PATH=/media/sam/1TB/research-pipeline/data/research.db
RP_LOG_LEVEL=INFO
```

**Behavior**: Warns and uses defaults when env vars are missing (development-friendly, no crashes on unconfigured dev machine).

### Component: Services

**Purpose**: Individual microservices that implement the paper processing pipeline.
**Location**: `/media/sam/1TB/research-pipeline/services/`
**Status**: All 6 services implemented and running in production.

| Service | Port | Purpose | External Dependencies |
|---------|------|---------|----------------------|
| Discovery | 8770 | arXiv API fetch + Semantic Scholar/CrossRef enrichment | arXiv API, Semantic Scholar API, CrossRef API |
| Analyzer | 8771 | Topic-agnostic LLM scoring (5 criteria, 0-1.0 scale) | LLM fallback chain |
| Extractor | 8772 | PDF text extraction + LaTeX formula regex | RAGAnything (:8767) |
| Validator | 8773 | Multi-CAS formula validation with consensus | CAS Microservice (:8769), SymPy |
| Codegen | 8774 | 5-layer LaTeX→code (C99/Rust/Python) + batch LLM explain | SymPy, LLM fallback chain |
| Orchestrator | 8775 | Pipeline coordination, per-stage timeouts, retry logic | All above services, Discord webhook |

#### Analyzer: Topic-Agnostic Scoring

The analyzer scores papers on 5 criteria (each 0.0-1.0):
- `topic_relevance` — configurable via `RP_ANALYZER_TOPIC` env var
- `mathematical_rigor`, `novelty`, `practical_applicability`, `data_quality`

Default topic: "Kelly criterion, optimal bet sizing, fractional Kelly, portfolio optimization".
Override with any research topic: `RP_ANALYZER_TOPIC="reinforcement learning, policy gradient"`.

#### Codegen: 5-Layer Parse Recovery

LaTeX→code conversion uses 5 cumulative layers to maximize success rate:

| Layer | Fix | Recovery |
|-------|-----|----------|
| 1 | Enhanced `clean_latex()` — sizing cmds, `\parallel`, sign subscripts | parse_latex failures |
| 2 | Multi-line split — `\\` lines, `\Rightarrow` prefix, equality chains | parse_latex failures |
| 3 | `Equality.rhs` extraction | codegen output_args failures (C99/Rust) |
| 4 | `pycode(strict=False)` fallback | Function objects not printable |
| 5 | LLM fallback (Python only) | Residual parse_latex failures |

**Batch explain**: Formulas are explained in chunks of 10 (configurable, max 25) via a single LLM call per chunk. No per-formula LLM fallback — if batch fails, codegen proceeds without explanations (circuit breaker).

**OOM prevention**: `gc.collect()` + `malloc_trim(0)` after each formula to force Python's pymalloc to return freed heap to OS. Prevents RSS monotonic growth on large batches.

### Component: Test Suite (`tests/`)

**Purpose**: Validates all services with unit, integration, e2e, and smoke tests.
**Location**: `/media/sam/1TB/research-pipeline/tests/`
**Results**: 685+ tests pass, 0 failures

**Structure**:
- `conftest.py` -- Shared fixtures: `memory_db`, `tmp_db_path`, `initialized_db`, `validated_formula_db`, `clean_env`, `sample_paper_row`, etc.
- `unit/` -- Fast tests (no I/O): `test_db.py`, `test_models.py`, `test_config.py`, `test_server.py`, `test_codegen.py`, `test_generators.py`, `test_llm.py`, `test_cli_providers.py`
- `integration/` -- DB + HTTP: `test_db_models.py`, `test_server_http.py`, `test_codegen_db.py`, `test_hardening.py`
- `e2e/` -- End-to-end with real services: `test_smoke_orchestrator.py`, `test_analyzer_e2e.py`
- `smoke/*.j2` -- 6 Jinja2 templates for service smoke tests (generated per-service at deploy time)

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
  +-- Fetch paper metadata from SQLite
  +-- LLM fallback chain for topic-agnostic 5-criteria scoring (0-1.0 each)
  +-- Topic set via RP_ANALYZER_TOPIC (default: Kelly criterion)
  +-- Route: avg_score >= threshold (0.7) -> analyzed, else -> rejected
  +-- UPDATE papers [stage=analyzed|rejected, score=N, prompt_version=v2]
         |
         v
  Extractor (:8772)
  +-- Send PDF to RAGAnything (:8767) for text extraction
  +-- Regex-based LaTeX formula extraction from text
  +-- INSERT formulas -> SQLite [stage=extracted]
         |
         v
  Validator (:8773)
  +-- For each formula:
  |   +-- Validate with SymPy (Python, local)
  |   +-- Validate with Maxima via CAS (:8769)
  |   +-- Validate with Wolfram Alpha API
  |   +-- Consensus scoring (2/3 agree = valid)
  +-- UPDATE formulas [stage=validated]
         |
         v
  Codegen (:8774)
  +-- Batch LLM explanation (chunks of 10, circuit breaker on failure)
  +-- 5-layer LaTeX parse recovery (clean_latex, multi-line, Equality.rhs)
  +-- C99 codegen via SymPy codegen("C99")
  +-- Rust codegen via SymPy codegen("Rust")
  +-- Python codegen via pycode() with LLM fallback (Layer 5)
  +-- OOM prevention: gc.collect() + malloc_trim(0) per formula
  +-- INSERT generated_code -> SQLite [stage=codegen]
         |
         v
  Orchestrator (:8775)
  +-- Mark pipeline complete [stage=complete]
  +-- Send Discord summary notification
```

## API Contract

All services implement these standard endpoints:

### GET /health
```json
{"status": "ok", "service": "discovery", "uptime_seconds": 3600.5}
```
Returns 200 always (if service is running). Used by Prometheus and Grafana.

### GET /status
```json
{
  "service": "discovery",
  "version": "0.1.0",
  "db_path": "/media/sam/1TB/research-pipeline/data/research.db",
  "uptime_seconds": 3600.5
}
```
Service-specific fields may be added beyond the base.

### POST /process
Service-specific. Request/response extend `ProcessRequest`/`ProcessResponse`.

### Error Format (all 4xx/5xx)
```json
{
  "error": "Human-readable message",
  "code": "INVALID_REQUEST",
  "details": {"field": "paper_id", "reason": "must be positive integer"}
}
```

| HTTP | Code | When |
|------|------|------|
| 400 | `INVALID_JSON` | Request body is not valid JSON |
| 400 | `MISSING_FIELD` | Required field missing |
| 400 | `INVALID_VALUE` | Field value fails validation |
| 404 | `NOT_FOUND` | Unknown endpoint |
| 422 | `PROCESSING_FAILED` | Service-specific processing error |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

## Service Port Map

| Port | Service | Status | Description |
|------|---------|--------|-------------|
| 8767 | RAGAnything | External (N8N_dev) | PDF processing |
| 8769 | CAS Microservice | External (N8N_dev) | Formula validation (Maxima engine) |
| 8770 | Discovery | Running | arXiv + Semantic Scholar/CrossRef |
| 8771 | Analyzer | Running | Topic-agnostic LLM scoring (fallback chain) |
| 8772 | Extractor | Running | RAGAnything PDF + LaTeX regex |
| 8773 | Validator | Running | Multi-CAS consensus |
| 8774 | Codegen | Running | 5-layer LaTeX→C99/Rust/Python + batch LLM explain |
| 8775 | Orchestrator | Running | Pipeline coordination + Discord + async /run |
| 11434 | Ollama | External | Local LLM (qwen3:8b) |

## Key Technical Decisions

### Decision 1: SQLite over PostgreSQL

- **Decision**: Use SQLite with WAL mode instead of PostgreSQL
- **Rationale**: Daily batch of ~10 papers does not justify PostgreSQL overhead. SQLite is zero-infra (file-based), easily backed up, and WAL mode supports the concurrent read pattern needed (orchestrator reads while a service writes).
- **Trade-offs**: No multi-server deployment possible; acceptable since all services run on the same Workstation (192.168.1.111)

### Decision 2: http.server (stdlib) over FastAPI/Flask

- **Decision**: Use Python's built-in `http.server` module with no web framework
- **Rationale**: Matches the proven CAS microservice pattern (1,090 LOC, running in production). Zero extra dependencies. KISS principle.
- **Trade-offs**: No async support, no auto-generated OpenAPI docs, manual JSON handling. Acceptable for synchronous daily batch processing.

### Decision 3: Microservices over Monolith

- **Decision**: 5 independent services + 1 orchestrator instead of a single process
- **Rationale**: User's explicit choice for resilience and independent replaceability. One failing service does not take down the pipeline. Each service can be restarted, debugged, or replaced independently.
- **Trade-offs**: More systemd units to manage, inter-service HTTP overhead. Mitigated by shared library reducing boilerplate.

### Decision 4: Monorepo with shared/ directory

- **Decision**: Single repository with a `shared/` package imported via PYTHONPATH
- **Rationale**: Single venv for all services, no packaging ceremony, simple imports. All code in one place for easy cross-service refactoring.
- **Trade-offs**: No independent versioning of shared library. Acceptable at current scale.

### Decision 5: Decorator-based route dispatch

- **Decision**: `@route("POST", "/process")` decorator instead of monolithic `do_POST`
- **Rationale**: Clean separation of routing from business logic. Each endpoint is a self-contained method. Inspired by Flask/FastAPI patterns but implemented in 14 lines.
- **Trade-offs**: Slightly "magic" (introspects function attributes). Well-documented to mitigate.

### Decision 6: JSON structured logging for Loki

- **Decision**: All log output as JSON (`{"timestamp", "level", "service", "msg"}`)
- **Rationale**: Direct integration with Loki via journald/Promtail. Structured logs enable querying by service, level, and time in Grafana.
- **Trade-offs**: Less readable in raw terminal output. Acceptable since production logs are consumed by Loki, not humans.

### Decision 7: Full independence from N8N

- **Decision**: SQLite file-based storage, no shared containers, tables, or references to N8N infrastructure
- **Rationale**: N8N crashed and lost all data. Clean break eliminates the single point of failure. CAS (:8769) and RAGAnything (:8767) continue as external services but are not coupled to N8N.

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `RP_{SERVICE}_PORT` | TCP port for a service | See port map above |
| `RP_DB_PATH` | Path to SQLite database | `./data/research.db` |
| `RP_LOG_LEVEL` | Logging level | `INFO` |
| `RP_DATA_DIR` | Directory for data files | `./data/` |
| `RP_LLM_FALLBACK_ORDER` | Comma-separated LLM provider order | `gemini_cli,codex_cli,claude_cli,openrouter,ollama` |
| `RP_CODEGEN_FALLBACK_ORDER` | Codegen-specific LLM override | Falls back to `RP_LLM_FALLBACK_ORDER` |
| `RP_CODEGEN_BATCH_SIZE` | Formulas per batch LLM explain call | `10` (clamped 5-25) |
| `RP_ANALYZER_TOPIC` | Scoring topic for analyzer | `Kelly criterion, optimal bet sizing, ...` |
| `RP_ANALYZER_THRESHOLD` | Min avg_score to pass analysis | `0.7` |
| `RP_ORCHESTRATOR_CODEGEN_TIMEOUT` | Codegen stage timeout (seconds) | `900` |

Services are started via dotenvx for secret injection:
```bash
dotenvx run -f .env -- python3 services/discovery/main.py
```

## Infrastructure

- **Host**: Workstation (192.168.1.111), Ubuntu
- **Process management**: systemd user services (one unit per microservice)
- **Daily trigger**: systemd timer at 8:00 AM activating the Orchestrator
- **Monitoring**: Prometheus process-exporter + Grafana dashboard + Loki structured logs
- **Alerts**: Discord webhook for pipeline completion/failure summaries
- **External services**: CAS (:8769), RAGAnything (:8767), Ollama (:11434) -- all on the same host

## AI Agent Integration

The primary consumers of these services are AI agents running `/research` and `/research-papers` commands.

**Contract requirements**:
1. Every response is valid JSON (no HTML error pages, no plain text)
2. `/process` is idempotent (same paper_id twice produces same result; `force` flag overrides)
3. Agents parse `code` field in errors to determine retry strategy
4. Each service includes `time_ms` in response for timeout calibration
5. Orchestrator accepts batch requests; individual services process one item at a time

**Recommended timeouts per service**:
| Service | Timeout | Reason |
|---------|---------|--------|
| Discovery | 30s | External API calls (arXiv, Semantic Scholar, CrossRef) |
| Analyzer | 60s | LLM inference via fallback chain |
| Extractor | 120s | PDF processing via RAGAnything |
| Validator | 90s | Multi-CAS consensus (3 engines) |
| Codegen | 900s | Batch LLM explain + SymPy codegen for ~37 formulas |

## Development Status

| Milestone | Status | Key Output |
|-----------|--------|------------|
| v1.0 Foundation (Phases 1-4) | Complete | Shared lib, SQLite schema, HTTP server, config, 103 tests |
| v2-v5 Discovery/Analyzer (Phases 5-12) | Complete | arXiv + enrichment, LLM scoring, systemd units |
| v6-v8 Extractor/Validator (Phases 13-25) | Complete | RAGAnything PDF, multi-CAS consensus, formula dedup |
| v9-v11 Codegen/Orchestrator (Phases 26-37) | Complete | 5-layer codegen, batch explain, async /run, e2e tests |

**Test suite**: 685+ tests (unit, integration, e2e), 0 failures.

**Dependencies** (from `pyproject.toml`):
- `pydantic>=2.0`, `sympy>=1.12`, `requests>=2.31` (runtime)
- `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-cov>=5.0` (dev)

## Related Documentation

- [PROJECT.md](../.planning/PROJECT.md) -- Project definition and requirements
- [ROADMAP.md](../.planning/ROADMAP.md) -- Phase roadmap and progress tracking
- [STATE.md](../.planning/STATE.md) -- Current state and accumulated decisions
- [Phase 01 ARCHITECTURE.md](../.planning/phases/01-research-design/ARCHITECTURE.md) -- Detailed design spec from Phase 1

---

*Architecture documented: 2026-02-10*
*Last validated: 2026-02-18 (685+ tests pass, all services running)*
*Auto-updated by architecture-validator agent*
