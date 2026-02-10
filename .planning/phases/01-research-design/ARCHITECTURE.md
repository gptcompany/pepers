# Research Pipeline Architecture

## 1. Overview

A set of 5 standalone Python microservices + 1 orchestrator that processes academic papers through a sequential pipeline: fetch, analyze, extract formulas, validate with CAS engines, and generate code. All services share a common library (`shared/`) for HTTP serving, data models, database access, and configuration.

```
                        ┌─────────────┐
                        │ Orchestrator│ (:8775)
                        │  daily 8AM  │
                        └──────┬──────┘
                               │ coordinates
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                   ▼
    ┌──────────────┐  ┌──────────────┐   ┌──────────────┐
    │  Discovery   │→ │   Analyzer   │ → │  Extractor   │
    │   (:8770)    │  │   (:8771)    │   │   (:8772)    │
    │  arXiv API   │  │ Ollama LLM   │   │ RAGAnything  │
    │ + enrichment │  │ + scoring    │   │ + LaTeX regex│
    └──────────────┘  └──────────────┘   └──────────────┘
                                                │
                               ┌────────────────┘
                               ▼
                      ┌──────────────┐   ┌──────────────┐
                      │  Validator   │ → │   Codegen    │
                      │   (:8773)    │   │   (:8774)    │
                      │ SymPy+CAS   │   │ Python+Rust  │
                      │  consensus  │   │  AST-based   │
                      └──────────────┘   └──────────────┘
```

Data flows left-to-right/top-to-bottom. Each service is independent, communicates via HTTP JSON.

## 2. Directory Structure

```
research-pipeline/
├── shared/                     # Shared library (all services import from here)
│   ├── __init__.py             # Package version, convenience imports
│   ├── db.py                   # SQLite connection management (WAL mode)
│   ├── models.py               # Pydantic data models (Paper, Formula, etc.)
│   ├── server.py               # Base HTTP server + route dispatch + JSON helpers
│   └── config.py               # Config loading from env vars + dotenvx
├── services/                   # Microservice implementations (one dir per service)
│   ├── discovery/              # (Phase 02+) arXiv fetch + enrichment
│   ├── analyzer/               # (Phase 02+) LLM analysis + scoring
│   ├── extractor/              # (Phase 02+) PDF → LaTeX extraction
│   ├── validator/              # (Phase 02+) Multi-CAS validation
│   ├── codegen/                # (Phase 02+) Code generation
│   └── orchestrator/           # (Phase 02+) Pipeline coordinator
├── tests/                      # Test suite
│   ├── test_db.py
│   ├── test_models.py
│   ├── test_server.py
│   └── test_config.py
├── data/                       # Runtime data (gitignored)
│   └── research.db             # SQLite database
├── systemd/                    # systemd unit files (Phase 02+)
├── .planning/                  # GSD planning artifacts
├── pyproject.toml              # Project metadata + dependencies
├── .python-version             # Python 3.11
└── .env                        # dotenvx encrypted secrets
```

## 3. Module Specifications

### shared/db.py — SQLite Database Layer

**Purpose:** Provide connection management for the shared SQLite database.

**Interface:**
- `get_connection(db_path) -> sqlite3.Connection` — WAL mode, foreign keys ON, Row factory
- `transaction(db_path) -> ContextManager[Connection]` — auto-commit/rollback
- `init_db(db_path) -> None` — create tables (idempotent)

**Design:**
- WAL mode enables concurrent reads (orchestrator reads while service writes)
- Foreign keys enforced at connection level (`PRAGMA foreign_keys = ON`)
- `sqlite3.Row` factory for dict-like access (`row["title"]`)
- Single connection per request — no pool needed for ~10 papers/day batch
- Schema defined as SQL string constant in module (no migration framework — YAGNI)

### shared/models.py — Pydantic Data Models

**Purpose:** Type-safe data transfer between services and database.

**Models:**
| Model | Purpose | Populated by |
|-------|---------|-------------|
| `Paper` | Academic paper metadata | Discovery service |
| `Formula` | Extracted LaTeX formula | Extractor service |
| `Validation` | CAS validation result | Validator service |
| `GeneratedCode` | Generated Python/Rust code | Codegen service |
| `ServiceStatus` | /health and /status response | All services |
| `ProcessRequest` | Base /process request | Service-specific |
| `ProcessResponse` | Base /process response | Service-specific |
| `ErrorResponse` | Standard error format | All services |

**Serialization strategy:**
- `.model_dump()` for SQLite INSERT (flat dict)
- `.model_dump_json()` for HTTP responses
- `Model.model_validate(dict)` for SQLite SELECT → model
- All datetime fields stored as ISO 8601 strings in SQLite

### shared/server.py — Base HTTP Server

**Purpose:** Reusable HTTP server with JSON handling, routing, and standard endpoints.

**Design (improves on CAS microservice patterns):**

| CAS Pattern | Shared Lib Improvement |
|-------------|----------------------|
| Monolithic do_POST/do_GET | `@route("POST", "/path")` decorator dispatch |
| Manual JSON encode/decode | `send_json()`, `read_json()` helpers |
| Bare 500 for all errors | Typed errors: 400, 404, 422, 500 with error codes |
| Logging suppressed | Python `logging` module, structured for Loki |
| KeyboardInterrupt only | SIGTERM handler for clean systemd stop |
| No /status endpoint | /health + /status auto-registered |

**Standard endpoints (auto-registered):**
```
GET /health → {"status": "ok", "service": "name", "uptime_seconds": N}
GET /status → {"service": "name", "version": "0.1.0", "db_path": "...", "last_processed": "..."}
POST /process → service-specific (each service implements this)
```

### shared/config.py — Configuration

**Purpose:** Load service configuration from environment variables.

**Env var naming:** `RP_{SERVICE}_{FIELD}` (RP = Research Pipeline)

Examples:
```bash
RP_DISCOVERY_PORT=8770
RP_ANALYZER_PORT=8771
RP_DB_PATH=/media/sam/1TB/research-pipeline/data/research.db
RP_LOG_LEVEL=INFO
RP_OLLAMA_URL=http://localhost:11434
```

**dotenvx integration:** Services started via `dotenvx run -f .env -- python3 services/discovery/main.py`

## 4. API Contract

All services MUST implement these endpoints:

### GET /health
```json
{"status": "ok", "service": "discovery", "uptime_seconds": 3600.5}
```
Returns 200 always (if service is running). Used by Prometheus process-exporter and Grafana.

### GET /status
```json
{
  "service": "discovery",
  "version": "0.1.0",
  "db_path": "/media/sam/1TB/research-pipeline/data/research.db",
  "last_processed": "2026-02-10T08:00:00Z",
  "papers_today": 7,
  "uptime_seconds": 3600.5
}
```
Returns 200 with detailed service info. Service-specific fields allowed beyond the base.

### POST /process
Service-specific. Request and response extend `ProcessRequest`/`ProcessResponse`.

**Request:**
```json
{"paper_id": 42, "force": false}
```

**Response (success):**
```json
{"success": true, "service": "discovery", "time_ms": 1234, "result": {...}}
```

**Response (error):**
```json
{"success": false, "service": "discovery", "time_ms": 500, "error": "arXiv API timeout"}
```

### Error Format (all 4xx/5xx)
```json
{
  "error": "Human-readable message",
  "code": "INVALID_REQUEST",
  "details": {"field": "paper_id", "reason": "must be positive integer"}
}
```

**Error codes:**
| HTTP | Code | When |
|------|------|------|
| 400 | `INVALID_JSON` | Request body is not valid JSON |
| 400 | `MISSING_FIELD` | Required field missing |
| 400 | `INVALID_VALUE` | Field value fails validation |
| 404 | `NOT_FOUND` | Unknown endpoint |
| 422 | `PROCESSING_FAILED` | Service-specific processing error |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

## 5. Design Decisions

| Decision | Rationale |
|----------|-----------|
| SQLite over PostgreSQL | ~10 papers/day, YAGNI, zero infra, file backup |
| http.server over FastAPI | Match CAS pattern, zero deps, KISS |
| Monorepo with shared/ | Single venv, PYTHONPATH import, no packaging |
| Pydantic v2 for models | Validation, serialization, type safety — one dependency |
| WAL mode for SQLite | Concurrent read access during pipeline execution |
| RP_ env var prefix | Avoid collisions with system/other service env vars |
| @route decorator dispatch | Clean separation of routing from business logic |
| Standard error format | AI agents need predictable error parsing |
| SIGTERM handling | Clean shutdown for systemd stop/restart |
| Ports 8770-8775 | Non-conflicting with CAS (:8769), RAGAnything (:8767) |

## 6. Service Port Map

| Port | Service | Description |
|------|---------|-------------|
| 8767 | RAGAnything | PDF processing (existing, in N8N_dev) |
| 8769 | CAS Microservice | Formula validation (existing, in N8N_dev) |
| 8770 | Discovery | arXiv fetch + Semantic Scholar/CrossRef enrichment |
| 8771 | Analyzer | LLM analysis (Ollama qwen3:8b) + relevance scoring |
| 8772 | Extractor | RAGAnything PDF → LaTeX formula extraction |
| 8773 | Validator | Multi-CAS validation (SymPy + Wolfram + Maxima) |
| 8774 | Codegen | Python (SymPy) + Rust (AST-based) code generation |
| 8775 | Orchestrator | Pipeline coordination + retry + Discord notifications |
| 11434 | Ollama | Local LLM (existing) |

## 7. Data Flow

```
Daily 8AM timer triggers Orchestrator (:8775)
         │
         ▼
  Discovery (:8770)
  ├── Query arXiv API (keywords: kelly criterion, portfolio optimization, ...)
  ├── Enrich via Semantic Scholar (citations, references)
  ├── Enrich via CrossRef (DOI metadata)
  └── INSERT papers → SQLite [stage=discovered]
         │
         ▼
  Analyzer (:8771)
  ├── Fetch paper metadata from SQLite
  ├── Send to Ollama qwen3:8b for analysis
  ├── 5-criteria relevance scoring (0-10 each)
  ├── Route: score >= threshold → continue, else → skip
  └── UPDATE papers [stage=analyzed, score=N]
         │
         ▼
  Extractor (:8772)
  ├── Send PDF to RAGAnything (:8767) for text extraction
  ├── Regex-based LaTeX formula extraction from text
  └── INSERT formulas → SQLite [stage=extracted]
         │
         ▼
  Validator (:8773)
  ├── For each formula:
  │   ├── Validate with SymPy (Python, local)
  │   ├── Validate with Maxima via CAS (:8769)
  │   ├── Validate with Wolfram Alpha API
  │   └── Consensus scoring (2/3 agree = valid)
  └── UPDATE formulas [stage=validated, consensus_score=N]
         │
         ▼
  Codegen (:8774)
  ├── LLM plain-language explanation of formula
  ├── Python codegen via SymPy symbolic → numeric
  ├── Rust codegen via AST-based transpilation
  └── INSERT generated_code → SQLite [stage=codegen]
         │
         ▼
  Orchestrator (:8775)
  ├── Mark pipeline complete [stage=complete]
  └── Send Discord summary notification
```

## 8. AI Agent Integration

The primary consumers of these services are AI agents running `/research` and `/research-papers` commands.

**Contract requirements for AI agents:**

1. **Predictable JSON responses** — Every response is valid JSON. No HTML error pages, no plain text.

2. **Idempotent /process** — Calling `/process` with the same `paper_id` twice produces the same result (or skips if already processed, controlled by `force` flag).

3. **Clear error codes** — Agents parse `code` field to determine retry strategy:
   - `INVALID_REQUEST` → don't retry (fix request)
   - `PROCESSING_FAILED` → retry with backoff
   - `INTERNAL_ERROR` → retry once, then alert

4. **Timeout guidance** — Each service includes `time_ms` in response. Agents should set timeouts:
   - Discovery: 30s (external API calls)
   - Analyzer: 60s (LLM inference)
   - Extractor: 120s (PDF processing)
   - Validator: 90s (multi-CAS consensus)
   - Codegen: 60s (LLM + transpilation)

5. **Batch support** — Orchestrator accepts batch requests. Individual services process one item at a time (simplicity, debuggability).

---

*Architecture designed: 2026-02-10*
*Reference: CAS microservice analysis in CAS-ANALYSIS.md*
*Vision: 01-CONTEXT.md*
