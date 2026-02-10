# Summary: 03-01 HTTP Server & Config

## What Was Done

Completed stub implementations in `shared/server.py` and `shared/config.py`, making the full shared library functional.

### shared/config.py (80 → 113 LOC)
- **`load_config(service_name)`**: Reads `RP_{SERVICE}_{FIELD}` env vars with sensible defaults
- Warnings logged when env vars are missing (not crashes)
- Supports: PORT, DB_PATH, LOG_LEVEL, DATA_DIR

### shared/server.py (115 → 296 LOC)
- **`route(method, path)` decorator**: Registers handlers via `_route` attribute on functions
- **`BaseHandler._dispatch`**: Dict-based route lookup, strips query strings, handles GET/POST
- **`BaseHandler.send_json`**: JSON response with Content-Type, Content-Length, `default=str` for datetimes
- **`BaseHandler.send_error_json`**: Standard `{"error", "code", "details"}` error format
- **`BaseHandler.read_json`**: Content-Length-based body read, 400 on empty/invalid JSON
- **`BaseHandler.log_message`**: Override → Python logging (no more stderr spam)
- **`BaseService.__init__`**: Injects service metadata into handler class, registers /health + /status
- **`BaseService.run`**: JSON logging setup, SIGTERM handler (main thread only), serve_forever
- **`JsonFormatter`**: Structured JSON logging for Loki/journald

### Built-in Endpoints
- `GET /health` → `{"status": "ok", "service": name, "uptime_seconds": N}`
- `GET /status` → `{"service", "version", "uptime_seconds", "db_path"}`
- Subclass can override by defining own `@route("GET", "/health")` etc.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| JSON structured logging | User choice — better Loki parsing |
| Warn + default for missing env vars | User choice — development-friendly |
| Graceful SIGTERM drain | User choice — finish current request, then stop |
| Thread-safe signal registration | `signal.signal()` only in main thread; allows thread-based testing |
| Query string stripping | `/health?foo=bar` matches `/health` route |

## Test Results

### Unit Tests (8/8 pass)
1. JsonFormatter produces valid JSON with service/level/msg
2. route decorator stores (method, path) tuple
3. /health returns status=ok with service name and uptime
4. /status returns service, version, db_path
5. Custom GET route (/ping) dispatches correctly
6. Custom POST route (/echo) parses JSON and returns response
7. Unknown path returns 404 with NOT_FOUND code
8. Invalid JSON body returns 400 with INVALID_JSON code

### Integration Tests (3/3 pass)
1. Config loads port from env var, server starts on that port, /health works
2. POST /process with paper_id returns success response
3. POST /process without paper_id returns 400 MISSING_FIELD error

## Files Modified
- `shared/config.py` — load_config implemented (+33 LOC)
- `shared/server.py` — full implementation (+181 LOC)

## Dependencies
- No new dependencies added (all stdlib: http.server, logging, json, signal, threading)

---
*Completed: 2026-02-10*
