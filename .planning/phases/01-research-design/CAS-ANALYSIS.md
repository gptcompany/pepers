# CAS Microservice Analysis

**Source:** `/media/sam/1TB/N8N_dev/scripts/cas_microservice.py` (405 LOC)
**Systemd:** `/home/sam/.config/systemd/user/cas-microservice.service`
**Port:** 8769

## Patterns to Keep

### 1. Single-file http.server (line 4)
```python
from http.server import HTTPServer, BaseHTTPRequestHandler
```
Simple, zero dependencies. The entire service is one file. This pattern scales well for focused microservices.

### 2. Consistent result dict structure (lines 78-87, 143-152, 305-315)
Every validator returns the same shape:
```python
result = {
    "cas": "maxima",
    "engine": "macsyma-lisp",
    "success": False,
    "input": latex_str,
    "simplified": None,
    "error": None,
    "time_ms": 0,
}
```
Predictable for consumers. Our shared lib should standardize response models via Pydantic.

### 3. Health endpoint (lines 52-65)
GET `/health` returns JSON with service status. Essential for monitoring (Prometheus/Grafana).

### 4. Timing instrumentation (lines 77, 136)
Every operation is timed with `time.time()` and returned as `time_ms`. Good for observability.

### 5. Subprocess with timeout (lines 113-119)
```python
proc = subprocess.run(["maxima", "--very-quiet"], input=maxima_code,
                      capture_output=True, text=True, timeout=10)
```
Timeout prevents hanging. Different engines get different timeouts (10s Maxima, 60s SageMath, 30s MATLAB).

### 6. systemd unit pattern
```ini
Type=simple
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
```
Simple, reliable. `PYTHONUNBUFFERED=1` ensures logs appear in journald immediately.

## Patterns to Improve

### 1. No proper route dispatch (lines 23, 52)
Route handling is just `do_POST`/`do_GET` with if/elif. The shared lib should provide a simple route registry:
```python
# Instead of monolithic do_POST:
@route("POST", "/validate")
def handle_validate(self, data): ...
```

### 2. Port hardcoded (line 19)
```python
PORT = 8769  # No env var fallback
```
Should be configurable: `PORT = int(os.environ.get("CAS_PORT", 8769))`

### 3. No /status endpoint
Only `/health` exists. Need `/status` with more detail (version, uptime, last processed, DB stats).

### 4. No structured error codes (lines 46-50)
All errors return 500 with free-text message. Should have:
- 400 for bad request (missing fields, invalid JSON)
- 404 for unknown endpoint
- 422 for validation errors
- 500 for internal errors
- Standard error format: `{"error": "msg", "code": "INVALID_CAS", "details": {}}`

### 5. Logging suppressed entirely (lines 70-72)
```python
def log_message(self, format, *args):
    pass  # Suppress default logging
```
Default http.server logging is noisy, but suppressing ALL logging is wrong. Should use Python `logging` module with structured format for Loki ingestion.

### 6. No request validation (line 29-30)
```python
latex = data.get("latex", "")
cas = data.get("cas", "maxima")
```
No check if `latex` is empty or if required fields are present. AI agents need clear error messages.

### 7. No graceful shutdown (lines 392-400)
Only handles KeyboardInterrupt. Should handle SIGTERM (systemd sends this on stop).

### 8. No Content-Length in responses
Responses don't set Content-Length header. Not critical but good practice.

## Anti-patterns to Avoid

### 1. Business logic mixed with HTTP handling (lines 23-50)
`do_POST` does JSON parsing, CAS dispatch, AND error handling in one method. The shared lib should separate:
- HTTP layer (parse request, send response)
- Business logic (service-specific processing)

### 2. Bare except catching everything (line 46)
```python
except Exception as e:
    self.send_response(500)
```
Should catch specific exceptions and return appropriate status codes.

### 3. Hardcoded external paths (line 349)
```python
matlab_path = "/media/sam/3TB-WDC/matlab2025/bin/matlab"
```
Should be in config, not source code.

### 4. No JSON parse error handling (line 28)
If body is not valid JSON, `json.loads()` raises ValueError which gets caught by the generic Exception handler as 500. Should be 400 Bad Request.

### 5. Import inside function (lines 224, 244, 264, 301)
`import re` and `import os` inside validator functions. Should be at module level.

---

*Analysis date: 2026-02-10*
*Source: CAS microservice at /media/sam/1TB/N8N_dev/scripts/cas_microservice.py*
