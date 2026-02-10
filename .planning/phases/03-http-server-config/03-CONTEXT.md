# Phase 03 Context: HTTP Server & Config

## Goal

Implement `shared/server.py` and `shared/config.py` — completing the stub functions with working code. After this phase, any microservice can subclass `BaseHandler`, add `@route` handlers, and run via `BaseService.run()`.

## Scope

### shared/server.py (stubs → working code)

1. **`route(method, path)` decorator** — Register handler methods on the class. Store routes as class-level registry. Dispatch in `do_GET`/`do_POST` by matching method+path.

2. **`BaseHandler.send_json(data, status)`** — JSON-serialize `data`, set Content-Type + Content-Length, send response.

3. **`BaseHandler.send_error_json(error, code, status, details)`** — Format as `{"error": ..., "code": ..., "details": ...}`, delegate to `send_json`.

4. **`BaseHandler.read_json()`** — Read Content-Length bytes, parse JSON. Return None and send 400 error if invalid/missing.

5. **`BaseHandler` route dispatch** — Override `do_GET`/`do_POST` to look up registered routes. Return 404 for unknown paths.

6. **Built-in /health and /status** — Auto-registered. /health returns `{"status": "ok", "service": name, "uptime_seconds": N}`. /status returns extended info (version, db_path, etc.).

7. **`BaseService.__init__` and `.run()`** — Create HTTPServer, setup SIGTERM handler, configure logging, run `serve_forever`.

### shared/config.py (stubs → working code)

1. **`load_config(service_name)`** — Read `RP_{SERVICE}_{FIELD}` env vars. Fall back to defaults. Log warning if important env var is missing.

## Decisions from Discussion

| Decision | Choice |
|----------|--------|
| Logging format | JSON strutturato per Loki (`{"timestamp", "level", "service", "msg"}`) |
| Missing env vars | Warn + default (log.warning, use default value) |
| SIGTERM handling | Graceful drain — finish current request, then shutdown. 5s timeout. |

## Technical Details

### JSON Structured Logging

```python
import logging, json, time

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "msg": record.getMessage(),
            "module": record.module,
        })
```

### Route Dispatch Pattern

```python
# Registry: dict of (method, path) -> handler_function
# Decorator stores on function, do_GET/do_POST looks up registry
_routes: dict[tuple[str, str], Callable] = {}

def route(method, path):
    def decorator(fn):
        fn._route = (method.upper(), path)
        return fn
    return decorator
```

### Graceful SIGTERM

```python
signal.signal(signal.SIGTERM, self._handle_sigterm)

def _handle_sigterm(self, signum, frame):
    logger.info("SIGTERM received, shutting down gracefully...")
    self.server.shutdown()  # finish current request, then stop
```

### Config Warning Pattern

```python
port_str = os.environ.get(f"RP_{prefix}_PORT", "")
if not port_str:
    logger.warning(f"RP_{prefix}_PORT not set, using default {default_port}")
    port = default_port
else:
    port = int(port_str)
```

## Inputs

- `shared/server.py` — Stubs with docstrings (115 LOC)
- `shared/config.py` — Stubs with docstrings (79 LOC)
- ARCHITECTURE.md — Complete spec for server.py and config.py interfaces
- CAS-ANALYSIS.md — Patterns to keep/improve from reference implementation

## Outputs

- `shared/server.py` — Fully implemented (~150-200 LOC)
- `shared/config.py` — Fully implemented (~60-80 LOC)

## Dependencies

- Phase 01: ARCHITECTURE.md (design reference)
- Phase 02: shared/db.py, shared/models.py (used by server for status endpoint)
- No new external dependencies (http.server, logging, json, signal, os are stdlib)

## Risks

- None significant. Standard Python patterns, well-documented in stdlib.
- Route dispatch is simple dict lookup, no edge cases expected.

---
*Context captured: 2026-02-10*
