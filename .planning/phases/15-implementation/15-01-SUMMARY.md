# Summary: Plan 15-01 — CAS Microservice Implementation

## Status: COMPLETE

## Deliverables

| File | LOC | Description |
|------|-----|-------------|
| `cas_service/engines/base.py` | 38 | BaseEngine ABC + EngineResult dataclass |
| `cas_service/preprocessing.py` | 104 | 4-phase LaTeX preprocessing pipeline |
| `cas_service/engines/sympy_engine.py` | 124 | SymPy parse_latex + simplify, ANTLR→Lark fallback, 5s timeout |
| `cas_service/engines/maxima_engine.py` | 185 | Maxima subprocess, LaTeX→Maxima conversion table, 10s timeout |
| `cas_service/main.py` | 242 | CASHandler (http.server), /validate /health /status /engines |
| `cas_service/__main__.py` | 5 | Entry point |
| `cas-service.service` | 16 | systemd unit file |
| `pyproject.toml` | 16 | sympy>=1.13, antlr4-python3-runtime==4.11.1 |
| **Total** | **698** | Target was ~500, extra due to complete error handling + LaTeX→Maxima conversion |

## Acceptance Criteria

- [x] `uv run python -m cas_service.main` starts on port 8769
- [x] `GET /health` returns ok
- [x] `POST /validate` with simple LaTeX returns SymPy + Maxima results
- [x] Preprocessing strips environments and normalizes commands
- [x] Engine errors return success=false with error message
- [x] Timeout handling works for both engines
- [x] Equation validation: `(x+1)^2 = x^2 + 2*x + 1` → valid (diff=0)
- [x] Invalid equation detection: `x^2 = x + 1` → is_valid=false

## Verified

- SymPy 1.14.0 with ANTLR backend
- Maxima 5.45.1 at /usr/bin/maxima
- Both engines return results in <500ms (after warmup)
- Error handling: parse failures, timeouts, empty expressions
