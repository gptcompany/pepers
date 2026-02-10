# Phase 04: Test Suite — Context

## Phase Goal

Comprehensive test suite for the shared library (816 LOC, 4 modules). Unit tests for each module, integration tests with real SQLite DB, endpoint tests for base HTTP server.

## User Preferences

- **Approach**: Test reali da zero (ignora template .j2 in tests/smoke/)
- **Coverage target**: >90%
- **Database strategy**: SQLite in-memory per unit tests, file temporaneo per integration tests
- **Framework**: pytest (already in dev deps)

## Modules Under Test

### 1. shared/db.py (171 LOC)
- `get_connection(db_path)` — WAL mode, foreign keys, row_factory
- `transaction(db_path)` — Context manager: commit/rollback/close
- `init_db(db_path)` — Idempotent schema creation (5 tables, 6 indexes)
- Constants: `SCHEMA`, `INDEXES`

**Test surface:**
- Connection returns Row factory
- WAL mode is set
- Foreign keys are enabled
- Transaction commits on success
- Transaction rolls back on exception
- init_db creates all 5 tables
- init_db creates all 6 indexes
- init_db is idempotent (run twice)
- schema_version is set to 1
- Parent directory auto-creation

### 2. shared/models.py (223 LOC)
- `PipelineStage` enum (7 values)
- `_parse_json_list(v)` — None→[], str→list, list→list
- `_parse_json_dict(v)` — None→None, str→dict, dict→dict
- `Paper` model with field validators (authors, categories, fields_of_study, crossref_data)
- `Formula` model with model_validator (auto latex_hash SHA-256)
- `Validation` model (straightforward)
- `GeneratedCode` model with metadata validator
- `ServiceStatus`, `ProcessRequest`, `ProcessResponse`, `ErrorResponse`

**Test surface:**
- PipelineStage enum values
- JSON list parsing: None, string, list, invalid
- JSON dict parsing: None, string, dict, invalid
- Paper creation with minimal fields
- Paper creation with all fields
- Paper JSON round-trip (validators trigger on string input)
- Formula auto-hash computation
- Formula hash not recomputed when provided
- Model validation errors (missing required fields)
- from_attributes=True (SQLite.Row compatibility)

### 3. shared/server.py (298 LOC)
- `JsonFormatter` — Structured JSON logging
- `route` decorator — Sets _route attribute
- `BaseHandler` — Route dispatch, JSON helpers, error responses
- `BaseService` — Server lifecycle, SIGTERM, logging setup

**Test surface:**
- JsonFormatter output format
- JsonFormatter with exception
- route decorator sets _route attribute
- _build_routes discovers decorated methods
- _dispatch routes to correct handler (GET/POST)
- _dispatch returns 404 for unknown paths
- _dispatch handles POST with JSON body
- send_json serialization + headers
- send_error_json format
- read_json with valid/empty/invalid body
- BaseService injects metadata into handler
- BaseService registers /health and /status
- /health response format
- /status response format (with/without db_path)
- Handler exception → 500 error response
- Query string stripping in path matching

### 4. shared/config.py (118 LOC)
- `Config` dataclass with defaults
- `load_config(service_name)` — Env var loading with RP_ prefix
- `SERVICE_PORTS` dict
- `DEFAULT_DB_PATH` constant

**Test surface:**
- Config dataclass defaults
- load_config with all env vars set
- load_config with no env vars (defaults)
- load_config with partial env vars
- Port lookup per service name
- Unknown service name defaults to 8770
- Log level uppercasing
- Data dir override

## Integration Test Scenarios

1. **DB + Models round-trip**: init_db → insert Paper via SQL → read with Paper.model_validate
2. **Server + DB**: Start server, POST data, verify in DB
3. **Full endpoint cycle**: Health/Status via HTTP client
4. **Config → Service**: load_config → BaseService init → verify port/name

## Existing Test Infrastructure

- `tests/smoke/` — 6 Jinja2 templates (NOT real tests, to be ignored)
- `pyproject.toml` — pytest>=8.0 in dev deps, pytest-asyncio>=0.23
- No pytest.ini or conftest.py configured yet
- No coverage tool configured (need pytest-cov)

## Dependencies Needed

- pytest>=8.0 (already in dev deps)
- pytest-cov (NEW — for coverage measurement)
- No additional deps needed (stdlib http.client for HTTP tests)

## Test Directory Structure (Proposed)

```
tests/
├── conftest.py          # Shared fixtures (db paths, cleanup)
├── unit/
│   ├── test_db.py       # db.py unit tests
│   ├── test_models.py   # models.py unit tests
│   ├── test_config.py   # config.py unit tests
│   └── test_server.py   # server.py unit tests
└── integration/
    ├── test_db_models.py    # DB + Pydantic round-trip
    └── test_server_http.py  # HTTP endpoint tests
```
