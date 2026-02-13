# Phase 14 Design: Validator Service + CAS Microservice

## Overview

This document specifies two components:

1. **CAS Microservice** — standalone repo (`cas-service/`), port 8769, manages SymPy + Maxima engines
2. **Validator Service** — `services/validator/` in research-pipeline, port 8773, orchestrates validation with consensus logic

The CAS service is **stateless** and accepts LaTeX formulas, returning per-engine validation results. The Validator service reads formulas from the DB, calls the CAS service, applies consensus logic, and writes results back.

---

## 1. CAS Microservice (Separate Repo)

### 1.1 Repo Structure

```
cas-service/
├── cas_service/
│   ├── __init__.py
│   ├── main.py              # CASHandler + main() entry point
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── base.py           # BaseEngine ABC
│   │   ├── sympy_engine.py   # SymPy parse_latex + simplify
│   │   └── maxima_engine.py  # Maxima subprocess wrapper
│   └── preprocessing.py      # LaTeX preprocessing pipeline
├── tests/
│   ├── __init__.py
│   ├── test_sympy_engine.py
│   ├── test_maxima_engine.py
│   ├── test_preprocessing.py
│   └── test_handler.py
├── pyproject.toml
├── README.md
└── cas-service.service        # systemd unit file
```

### 1.2 API Contract

#### `POST /validate`

Validate a LaTeX formula against one or more CAS engines.

**Request:**
```json
{
  "latex": "\\frac{d}{dx} x^2 = 2x",
  "engines": ["sympy", "maxima"]
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `latex` | string | yes | — | Raw LaTeX formula |
| `engines` | string[] | no | `["sympy", "maxima"]` | Engines to run |

**Response (200):**
```json
{
  "results": [
    {
      "engine": "sympy",
      "success": true,
      "is_valid": true,
      "simplified": "2*x",
      "original_parsed": "Derivative(x**2, x)",
      "time_ms": 45
    },
    {
      "engine": "maxima",
      "success": true,
      "is_valid": true,
      "simplified": "2*x",
      "original_parsed": "diff(x^2, x)",
      "time_ms": 248
    }
  ],
  "latex_preprocessed": "\\frac{d}{dx} x^2 = 2x",
  "time_ms": 293
}
```

**Response per-engine result fields:**

| Field | Type | Description |
|-------|------|-------------|
| `engine` | string | Engine name (`"sympy"` or `"maxima"`) |
| `success` | bool | `true` if engine executed without error |
| `is_valid` | bool\|null | `true` if formula parses and simplifies, `null` if engine errored |
| `simplified` | string\|null | Simplified form of the formula, `null` on error |
| `original_parsed` | string\|null | Engine's internal representation |
| `time_ms` | int | Execution time for this engine |
| `error` | string\|null | Error message if `success=false` |

**Error Response (400):**
```json
{
  "error": "latex field is required",
  "code": "INVALID_REQUEST"
}
```

**Error Response (422):**
```json
{
  "error": "Unknown engine: wolfram",
  "code": "UNKNOWN_ENGINE",
  "details": {"available": ["sympy", "maxima"]}
}
```

#### `GET /health`

```json
{"status": "ok", "service": "cas-service", "uptime_seconds": 123.4}
```

#### `GET /status`

```json
{
  "service": "cas-service",
  "version": "0.1.0",
  "uptime_seconds": 123.4,
  "engines": {
    "sympy": {"available": true, "version": "1.13"},
    "maxima": {"available": true, "version": "5.46", "path": "/usr/bin/maxima"}
  }
}
```

#### `GET /engines`

```json
{
  "engines": [
    {"name": "sympy", "available": true, "description": "SymPy parse_latex + simplify"},
    {"name": "maxima", "available": true, "description": "Maxima CAS subprocess"}
  ]
}
```

### 1.3 Engine Abstraction

```python
# cas_service/engines/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EngineResult:
    """Result from a single CAS engine."""
    engine: str
    success: bool
    is_valid: bool | None = None
    simplified: str | None = None
    original_parsed: str | None = None
    error: str | None = None
    time_ms: int = 0


class BaseEngine(ABC):
    """Abstract base class for CAS engines."""

    name: str = "base"

    @abstractmethod
    def validate(self, latex: str) -> EngineResult:
        """Validate a preprocessed LaTeX formula.

        Args:
            latex: Preprocessed LaTeX string (environments stripped, normalized).

        Returns:
            EngineResult with validation outcome.
        """
        ...

    def is_available(self) -> bool:
        """Check if this engine is available on the system."""
        return True

    def get_version(self) -> str:
        """Return engine version string."""
        return "unknown"
```

### 1.4 SymPy Engine

```python
# cas_service/engines/sympy_engine.py
class SympyEngine(BaseEngine):
    name = "sympy"

    def validate(self, latex: str) -> EngineResult:
        """Parse LaTeX with sympy.parsing.latex.parse_latex, then simplify.

        Steps:
        1. parse_latex(latex) → SymPy expression
        2. simplify(expr) → simplified form
        3. If equation (contains =): check simplify(lhs - rhs) == 0

        Error handling:
        - LaTeXParsingError → success=False, error="parse failed: ..."
        - SympifyError → success=False, error="simplify failed: ..."
        - Timeout (5s) → success=False, error="timeout"
        """
        ...
```

**Key implementation notes:**
- Uses `antlr4-python3-runtime==4.11.1` (ANTLR backend, default)
- Fallback to Lark backend if ANTLR fails: `parse_latex(latex, backend='lark')`
- Equation detection: split on `=` and test `simplify(lhs - rhs) == 0`
- 5-second timeout via `signal.alarm` (Unix only, adequate for Workstation)

### 1.5 Maxima Engine

```python
# cas_service/engines/maxima_engine.py
class MaximaEngine(BaseEngine):
    name = "maxima"

    def __init__(self, maxima_path: str = "/usr/bin/maxima", timeout: int = 10):
        self.maxima_path = maxima_path
        self.timeout = timeout

    def validate(self, latex: str) -> EngineResult:
        """Convert LaTeX to Maxima syntax, run simplification via subprocess.

        Steps:
        1. Convert LaTeX → Maxima syntax (manual mapping)
        2. Run: echo "tex(ratsimp({expr}));" | maxima --very-quiet
        3. Parse Maxima output
        4. If equation: check is(equal(lhs, rhs))

        Error handling:
        - subprocess.TimeoutExpired → success=False, error="timeout"
        - Non-zero exit → success=False, error="maxima error: ..."
        - Empty output → success=False, error="no output"
        """
        ...
```

**Key implementation notes:**
- Maxima called via `subprocess.run()` with `timeout` parameter
- If subprocess hangs past timeout: `SIGKILL` fallback (subprocess.run handles this)
- LaTeX → Maxima conversion: manual mapping of common constructs
  - `\frac{a}{b}` → `a/b`
  - `\sqrt{x}` → `sqrt(x)`
  - `\sin`, `\cos`, etc. → `sin`, `cos`
  - `x^{n}` → `x^n`
- Maxima installed at `/usr/bin/maxima` (apt package, already on Workstation)

### 1.6 LaTeX Preprocessing Pipeline

```python
# cas_service/preprocessing.py
def preprocess_latex(latex: str) -> str:
    """5-phase LaTeX preprocessing pipeline.

    Converts raw LaTeX from papers into CAS-parseable form.
    """
    result = latex
    result = strip_environments(result)       # Phase 1
    result = remove_typographical(result)      # Phase 2
    result = normalize_synonyms(result)        # Phase 3
    result = clean_whitespace(result)          # Phase 4
    return result
```

#### Phase 1: Strip Environments
Remove math environment wrappers, keeping only the formula content.

```python
ENVIRONMENT_PATTERNS = [
    r"\\begin\{equation\*?\}",    r"\\end\{equation\*?\}",
    r"\\begin\{align\*?\}",       r"\\end\{align\*?\}",
    r"\\begin\{gather\*?\}",      r"\\end\{gather\*?\}",
    r"\\begin\{multline\*?\}",    r"\\end\{multline\*?\}",
    r"\\begin\{eqnarray\*?\}",    r"\\end\{eqnarray\*?\}",
    r"\\\[",                       r"\\\]",
    r"\$\$",                       r"\$",
]
```

#### Phase 2: Remove Typographical Commands
Strip commands that are visual-only and have no mathematical meaning.

```python
STRIP_COMMANDS = [
    r"\\left",  r"\\right",
    r"\\displaystyle",  r"\\textstyle",  r"\\scriptstyle",
    r"\\Big",  r"\\big",  r"\\bigg",  r"\\Bigg",
    r"\\,",  r"\\;",  r"\\:",  r"\\!",  r"\\quad",  r"\\qquad",
    r"&",  r"\\\\",  r"\\nonumber",  r"\\label\{[^}]*\}",
    r"\\tag\{[^}]*\}",
]

# Font commands: extract content
FONT_COMMANDS = [
    r"\\mathrm\{([^}]*)\}",    # \mathrm{text} → text
    r"\\mathbf\{([^}]*)\}",
    r"\\mathit\{([^}]*)\}",
    r"\\text\{([^}]*)\}",
    r"\\textit\{([^}]*)\}",
    r"\\boldsymbol\{([^}]*)\}",
    r"\\operatorname\{([^}]*)\}",
]
```

#### Phase 3: Normalize Synonyms
Map alternative LaTeX commands to their canonical forms.

```python
SYNONYMS = {
    r"\\dfrac":  r"\\frac",
    r"\\tfrac":  r"\\frac",
    r"\\ge":     r"\\geq",
    r"\\le":     r"\\leq",
    r"\\ne":     r"\\neq",
    r"\\to":     r"\\rightarrow",
    r"\\gets":   r"\\leftarrow",
    r"\\land":   r"\\wedge",
    r"\\lor":    r"\\vee",
    r"\\lnot":   r"\\neg",
    r"\\infty":  r"\\infty",   # identity (ensure consistent)
    r"\\cdot":   r"*",          # explicit multiplication
    r"\\times":  r"*",
}
```

#### Phase 4: Clean Whitespace
Collapse multiple spaces, trim, remove redundant braces.

```python
def clean_whitespace(latex: str) -> str:
    result = re.sub(r"\s+", " ", latex).strip()
    # Remove redundant outer braces: {expr} → expr (only if single group)
    if result.startswith("{") and result.endswith("}"):
        inner = result[1:-1]
        if inner.count("{") == inner.count("}"):
            result = inner
    return result
```

### 1.7 CAS Handler

```python
# cas_service/main.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time

from cas_service.engines.sympy_engine import SympyEngine
from cas_service.engines.maxima_engine import MaximaEngine
from cas_service.preprocessing import preprocess_latex


# Engine registry (initialized once at startup)
ENGINES = {}


class CASHandler(BaseHTTPRequestHandler):
    """HTTP handler for CAS microservice.

    Note: Does NOT use shared.server.BaseHandler since this is a
    separate repo. Uses stdlib http.server directly, same KISS pattern.
    """

    def do_POST(self):
        if self.path == "/validate":
            self._handle_validate()
        else:
            self._send_error("Not found", "NOT_FOUND", 404)

    def do_GET(self):
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/status":
            self._handle_status()
        elif self.path == "/engines":
            self._handle_engines()
        else:
            self._send_error("Not found", "NOT_FOUND", 404)

    def _handle_validate(self):
        data = self._read_json()
        if data is None:
            return

        latex = data.get("latex")
        if not latex:
            self._send_error("latex field is required", "INVALID_REQUEST", 400)
            return

        engines_requested = data.get("engines", ["sympy", "maxima"])

        # Validate engine names
        unknown = [e for e in engines_requested if e not in ENGINES]
        if unknown:
            self._send_error(
                f"Unknown engine: {', '.join(unknown)}",
                "UNKNOWN_ENGINE", 422,
                {"available": list(ENGINES.keys())}
            )
            return

        start = time.time()
        preprocessed = preprocess_latex(latex)

        results = []
        for engine_name in engines_requested:
            engine = ENGINES[engine_name]
            result = engine.validate(preprocessed)
            results.append({
                "engine": result.engine,
                "success": result.success,
                "is_valid": result.is_valid,
                "simplified": result.simplified,
                "original_parsed": result.original_parsed,
                "error": result.error,
                "time_ms": result.time_ms,
            })

        elapsed = int((time.time() - start) * 1000)
        self._send_json({
            "results": results,
            "latex_preprocessed": preprocessed,
            "time_ms": elapsed,
        })

    # ... _handle_health, _handle_status, _handle_engines,
    #     _send_json, _send_error, _read_json (same stdlib pattern)
```

### 1.8 Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `CAS_PORT` | `8769` | HTTP listen port |
| `CAS_MAXIMA_PATH` | `/usr/bin/maxima` | Path to Maxima binary |
| `CAS_MAXIMA_TIMEOUT` | `10` | Maxima subprocess timeout (seconds) |
| `CAS_SYMPY_TIMEOUT` | `5` | SymPy parse/simplify timeout (seconds) |
| `CAS_LOG_LEVEL` | `INFO` | Logging level |

### 1.9 systemd Unit File

```ini
# cas-service.service
[Unit]
Description=CAS Microservice (SymPy + Maxima)
After=network.target

[Service]
Type=simple
User=sam
WorkingDirectory=/media/sam/1TB/cas-service
ExecStart=/home/sam/.local/bin/uv run python -m cas_service.main
Restart=on-failure
RestartSec=5
Environment=CAS_PORT=8769
Environment=CAS_MAXIMA_PATH=/usr/bin/maxima
Environment=CAS_LOG_LEVEL=INFO

[Install]
WantedBy=multi-user.target
```

---

## 2. Validator Service (research-pipeline)

### 2.1 File Structure

```
services/validator/
├── __init__.py
├── main.py                # ValidatorHandler + main() entry point
├── cas_client.py           # HTTP client for CAS microservice
└── consensus.py            # Consensus logic module
```

### 2.2 ValidatorHandler

```python
# services/validator/main.py
from shared.server import BaseHandler, BaseService, route
from shared.config import load_config
from shared.db import init_db, transaction
from shared.models import Validation, PipelineStage

from services.validator.cas_client import CASClient
from services.validator.consensus import apply_consensus, ConsensusResult


class ValidatorHandler(BaseHandler):
    """Handler for the Validator service."""

    cas_url: str = "http://localhost:8769"
    max_formulas_default: int = 50
    engines: list[str] = ["sympy", "maxima"]

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict | None:
        """Validate extracted formulas via CAS service.

        Request body:
          {
            "paper_id": 123,          # optional: validate formulas for one paper
            "formula_id": 456,        # optional: validate a single formula
            "max_formulas": 50,       # optional: limit batch size
            "force": false,           # optional: re-validate already validated
            "engines": ["sympy", "maxima"]  # optional: override default engines
          }

        Response:
          {
            "success": true,
            "service": "validator",
            "formulas_processed": 10,
            "formulas_valid": 8,
            "formulas_invalid": 1,
            "formulas_unparseable": 1,
            "errors": [],
            "time_ms": 5200
          }
        """
        ...
```

### 2.3 Processing Flow

```
handle_process(data)
│
├─ 1. Query formulas from DB (stage='extracted')
│     _query_formulas(db_path, paper_id, formula_id, max, force)
│
├─ 2. For each formula:
│  │
│  ├─ 2a. Call CAS service
│  │      cas_client.validate(formula.latex, engines)
│  │      → returns list of per-engine results
│  │
│  ├─ 2b. Store per-engine Validation records
│  │      _store_validations(db_path, formula_id, engine_results)
│  │
│  ├─ 2c. Apply consensus logic
│  │      consensus.apply_consensus(engine_results)
│  │      → ConsensusResult (valid|invalid|partial|unparseable)
│  │
│  └─ 2d. Update formula stage
│         _update_formula_stage(db_path, formula_id, consensus_result)
│         extracted → validated | failed
│
└─ 3. Return summary
```

### 2.4 CAS Client Module

```python
# services/validator/cas_client.py
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EngineResult:
    """Result from a single CAS engine (mirrors CAS service response)."""
    engine: str
    success: bool
    is_valid: bool | None = None
    simplified: str | None = None
    original_parsed: str | None = None
    error: str | None = None
    time_ms: int = 0


@dataclass
class CASResponse:
    """Full response from CAS service /validate endpoint."""
    results: list[EngineResult]
    latex_preprocessed: str
    time_ms: int


class CASClient:
    """HTTP client for the CAS microservice."""

    def __init__(self, base_url: str = "http://localhost:8769", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def validate(self, latex: str, engines: list[str] | None = None) -> CASResponse:
        """Send a formula to the CAS service for validation.

        Args:
            latex: Raw LaTeX formula string.
            engines: List of engine names. None = use CAS default.

        Returns:
            CASResponse with per-engine results.

        Raises:
            CASServiceError: If CAS service is unreachable or returns error.
        """
        payload = {"latex": latex}
        if engines:
            payload["engines"] = engines

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/validate",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as e:
            raise CASServiceError(f"CAS service unreachable: {e}") from e
        except urllib.error.HTTPError as e:
            error_body = json.loads(e.read())
            raise CASServiceError(
                f"CAS error {e.code}: {error_body.get('error', 'unknown')}"
            ) from e

        results = [
            EngineResult(
                engine=r["engine"],
                success=r["success"],
                is_valid=r.get("is_valid"),
                simplified=r.get("simplified"),
                original_parsed=r.get("original_parsed"),
                error=r.get("error"),
                time_ms=r.get("time_ms", 0),
            )
            for r in body["results"]
        ]

        return CASResponse(
            results=results,
            latex_preprocessed=body["latex_preprocessed"],
            time_ms=body["time_ms"],
        )

    def health(self) -> bool:
        """Check if CAS service is healthy."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                return body.get("status") == "ok"
        except Exception:
            return False


class CASServiceError(Exception):
    """Raised when CAS service is unreachable or returns an error."""
    pass
```

**Note:** Uses `urllib.request` (stdlib) instead of `requests` — consistent with project's no-external-deps-for-HTTP philosophy.

### 2.5 Consensus Logic Module

```python
# services/validator/consensus.py
from dataclasses import dataclass
from enum import Enum


class ConsensusOutcome(str, Enum):
    VALID = "valid"           # All engines agree formula is valid
    INVALID = "invalid"       # Engines disagree or explicitly invalid
    PARTIAL = "partial"       # One engine errored, other succeeded
    UNPARSEABLE = "unparseable"  # All engines failed to parse


@dataclass
class ConsensusResult:
    outcome: ConsensusOutcome
    detail: str               # Human-readable explanation
    engine_count: int         # Number of engines that ran
    agree_count: int          # Number that agree on is_valid


def apply_consensus(engine_results: list) -> ConsensusResult:
    """Apply consensus logic to per-engine validation results.

    Decision matrix (2 engines: SymPy + Maxima):

    | SymPy      | Maxima     | Outcome      | Detail                    |
    |------------|------------|--------------|---------------------------|
    | valid      | valid      | VALID        | Both engines agree        |
    | valid      | invalid    | INVALID      | Engines disagree          |
    | invalid    | valid      | INVALID      | Engines disagree          |
    | invalid    | invalid    | INVALID      | Both agree invalid        |
    | valid      | error      | PARTIAL      | Only SymPy succeeded      |
    | error      | valid      | PARTIAL      | Only Maxima succeeded     |
    | invalid    | error      | PARTIAL      | SymPy says invalid, Maxima errored |
    | error      | invalid    | PARTIAL      | Maxima says invalid, SymPy errored |
    | error      | error      | UNPARSEABLE  | Neither engine could parse |

    Rules:
    1. Both succeed + agree → VALID or INVALID
    2. Both succeed + disagree → INVALID (needs review)
    3. One errors → PARTIAL (not conclusive)
    4. Both error → UNPARSEABLE (skip, not failed)
    """
    successful = [r for r in engine_results if r.success]
    failed = [r for r in engine_results if not r.success]

    if len(successful) == 0:
        # All engines failed to parse
        return ConsensusResult(
            outcome=ConsensusOutcome.UNPARSEABLE,
            detail=f"All {len(engine_results)} engines failed to parse",
            engine_count=len(engine_results),
            agree_count=0,
        )

    if len(failed) > 0 and len(successful) > 0:
        # Mixed: some succeeded, some failed
        ok_engine = successful[0]
        return ConsensusResult(
            outcome=ConsensusOutcome.PARTIAL,
            detail=f"Only {ok_engine.engine} succeeded, {len(failed)} engine(s) errored",
            engine_count=len(engine_results),
            agree_count=1,
        )

    # All engines succeeded — check agreement
    valid_results = [r for r in successful if r.is_valid]
    invalid_results = [r for r in successful if not r.is_valid]

    if len(valid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.VALID,
            detail=f"All {len(successful)} engines agree: valid",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    if len(invalid_results) == len(successful):
        return ConsensusResult(
            outcome=ConsensusOutcome.INVALID,
            detail=f"All {len(successful)} engines agree: invalid",
            engine_count=len(engine_results),
            agree_count=len(successful),
        )

    # Disagreement
    return ConsensusResult(
        outcome=ConsensusOutcome.INVALID,
        detail=f"Engines disagree: {len(valid_results)} valid, {len(invalid_results)} invalid",
        engine_count=len(engine_results),
        agree_count=max(len(valid_results), len(invalid_results)),
    )
```

### 2.6 DB Operations

```python
# In services/validator/main.py (module-level helper functions)

def _query_formulas(db_path: str, paper_id: int | None,
                    formula_id: int | None, max_formulas: int,
                    force: bool) -> list[dict]:
    """Query formulas ready for validation.

    Args:
        paper_id: Filter by paper. None = all papers.
        formula_id: Filter by specific formula. None = batch mode.
        max_formulas: Limit batch size.
        force: If True, also include already-validated formulas.
    """
    with transaction(db_path) as conn:
        if formula_id:
            cursor = conn.execute(
                "SELECT * FROM formulas WHERE id = ?", (formula_id,)
            )
        elif paper_id:
            stages = "('extracted', 'validated')" if force else "('extracted',)"
            cursor = conn.execute(
                f"SELECT * FROM formulas WHERE paper_id = ? AND stage IN {stages} LIMIT ?",
                (paper_id, max_formulas),
            )
        else:
            stages = "('extracted', 'validated')" if force else "('extracted',)"
            cursor = conn.execute(
                f"SELECT * FROM formulas WHERE stage IN {stages} LIMIT ?",
                (max_formulas,),
            )
        return [dict(row) for row in cursor.fetchall()]


def _store_validations(db_path: str, formula_id: int,
                       engine_results: list) -> None:
    """Store per-engine validation results in the validations table.

    One row per engine per formula. Overwrites existing results
    for the same formula+engine combination.
    """
    with transaction(db_path) as conn:
        for r in engine_results:
            # Delete existing validation for this formula+engine
            conn.execute(
                "DELETE FROM validations WHERE formula_id = ? AND engine = ?",
                (formula_id, r.engine),
            )
            conn.execute(
                """INSERT INTO validations
                   (formula_id, engine, is_valid, result, error, time_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (formula_id, r.engine, r.is_valid, r.simplified, r.error, r.time_ms),
            )


def _update_formula_stage(db_path: str, formula_id: int,
                          consensus: ConsensusResult) -> None:
    """Update formula stage based on consensus outcome.

    Mapping:
      VALID → stage='validated'
      INVALID → stage='validated' (still validated, just invalid)
      PARTIAL → stage='validated' (partial info is still a result)
      UNPARSEABLE → stage='extracted' (leave as-is, don't fail)
    """
    if consensus.outcome == ConsensusOutcome.UNPARSEABLE:
        # Don't change stage — formula couldn't be parsed by any engine
        # It's not a failure, just unparseable
        return

    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'validated' WHERE id = ?",
            (formula_id,),
        )


def _mark_formula_failed(db_path: str, formula_id: int, error: str) -> None:
    """Mark a formula as failed (CAS service error, not parse error)."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'failed', error = ? WHERE id = ?",
            (f"validator: {error}", formula_id),
        )
```

### 2.7 Service Entry Point

```python
# services/validator/main.py

import os
from shared.server import BaseService
from shared.config import load_config
from shared.db import init_db


def main() -> None:
    config = load_config("validator")
    init_db(config.db_path)

    # Set handler config from environment
    ValidatorHandler.cas_url = os.environ.get(
        "RP_VALIDATOR_CAS_URL", "http://localhost:8769"
    )
    ValidatorHandler.max_formulas_default = int(
        os.environ.get("RP_VALIDATOR_MAX_FORMULAS", "50")
    )
    engines_str = os.environ.get("RP_VALIDATOR_ENGINES", "sympy,maxima")
    ValidatorHandler.engines = [e.strip() for e in engines_str.split(",")]

    service = BaseService(
        "validator",
        config.port,
        ValidatorHandler,
        str(config.db_path),
    )
    service.run()


if __name__ == "__main__":
    main()
```

### 2.8 Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RP_VALIDATOR_PORT` | `8773` | HTTP listen port |
| `RP_VALIDATOR_CAS_URL` | `http://localhost:8769` | CAS microservice URL |
| `RP_VALIDATOR_MAX_FORMULAS` | `50` | Max formulas per batch |
| `RP_VALIDATOR_ENGINES` | `sympy,maxima` | Comma-separated engine list |
| `RP_DB_PATH` | `data/research.db` | Shared SQLite database path |
| `RP_LOG_LEVEL` | `INFO` | Logging level |

---

## 3. Data Flow & Schema

### 3.1 Pipeline Stage Transitions

```
              Extractor               Validator
papers     ─────────────► formulas ──────────────► validations
(analyzed)                (extracted)               (per-engine)
                                      │
                                      ▼
                              formulas stage update
                              extracted → validated
                              extracted → failed (CAS error only)
                              extracted → extracted (unparseable, no change)
```

### 3.2 Input

Formulas table where `stage = 'extracted'`:

```sql
SELECT id, paper_id, latex, latex_hash, formula_type, context
FROM formulas
WHERE stage = 'extracted'
LIMIT 50;
```

### 3.3 Output

Validations table (one row per formula per engine):

```sql
-- Existing schema, no migration needed
CREATE TABLE IF NOT EXISTS validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id INTEGER NOT NULL REFERENCES formulas(id),
    engine TEXT NOT NULL,          -- "sympy" | "maxima"
    is_valid INTEGER,              -- 1=valid, 0=invalid, NULL=error
    result TEXT,                   -- simplified formula string
    error TEXT,                    -- error message if engine failed
    time_ms INTEGER,               -- engine execution time
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_validations_formula_id ON validations(formula_id);
```

### 3.4 Stage Transitions

| Consensus Outcome | Formula Stage | Rationale |
|-------------------|---------------|-----------|
| VALID | `validated` | Formula confirmed valid by all engines |
| INVALID | `validated` | Validation completed, result is "invalid" |
| PARTIAL | `validated` | Partial validation is still a result |
| UNPARSEABLE | `extracted` (no change) | Not a failure — formula may be valid but unparseable by current engines |
| CAS service error | `failed` | Infrastructure error, not formula issue |

### 3.5 No Schema Migration Needed

The existing `validations` table (created in `shared/db.py`) already has all required columns. The `Validation` model in `shared/models.py` maps directly to this table. No migration is needed.

---

## 4. Error Handling Matrix

| Error | Source | HTTP Code | Behavior |
|-------|--------|-----------|----------|
| Empty LaTeX | Validator | — | Skip formula, log warning |
| CAS service unreachable | CAS client | — | Mark formula as `failed`, continue batch |
| CAS service 4xx | CAS client | — | Mark formula as `failed`, log error |
| CAS service 5xx | CAS client | — | Mark formula as `failed`, retry next batch |
| SymPy parse_latex fails | CAS engine | — | Return `success=false` in engine result |
| SymPy timeout (5s) | CAS engine | — | Return `success=false, error="timeout"` |
| Maxima subprocess timeout | CAS engine | — | SIGKILL + return `success=false, error="timeout"` |
| Maxima non-zero exit | CAS engine | — | Return `success=false` with stderr |
| Maxima empty output | CAS engine | — | Return `success=false, error="no output"` |
| Invalid engine name | CAS handler | 422 | Return error with available engines list |
| Missing `latex` field | CAS handler | 400 | Return `INVALID_REQUEST` error |
| Invalid JSON body | Both handlers | 400 | Return `INVALID_JSON` error |
| DB write failure | Validator | 500 | Log, skip formula, continue batch |
| No formulas to process | Validator | 200 | Return success with `formulas_processed=0` |

### Error Categories

1. **Infrastructure errors** (CAS unreachable, DB failure): Mark formula as `failed`, continue batch
2. **Engine errors** (parse/timeout): Included in consensus as `success=false`, may result in `PARTIAL` or `UNPARSEABLE`
3. **Client errors** (bad request): Return 4xx immediately
4. **No-op** (no formulas): Return 200 with zero counts

---

## 5. Validation Report Format

The `/process` endpoint returns a summary report:

```json
{
  "success": true,
  "service": "validator",
  "formulas_processed": 10,
  "formulas_valid": 7,
  "formulas_invalid": 1,
  "formulas_partial": 1,
  "formulas_unparseable": 1,
  "formulas_failed": 0,
  "errors": [],
  "time_ms": 5200,
  "details": [
    {
      "formula_id": 42,
      "latex_hash": "abc123...",
      "consensus": "valid",
      "engines": {
        "sympy": {"success": true, "is_valid": true, "time_ms": 45},
        "maxima": {"success": true, "is_valid": true, "time_ms": 248}
      }
    }
  ]
}
```

The `details` array is included only when processing ≤10 formulas (single paper or formula_id mode). For large batches, only summary counts are returned to keep response size manageable.

---

## 6. Dependencies

### CAS Microservice (new repo)

```toml
# pyproject.toml
[project]
name = "cas-service"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sympy>=1.13",
    "antlr4-python3-runtime==4.11.1",
]
```

System dependency: `maxima` (apt package, already installed on Workstation).

### Validator Service (research-pipeline)

No new pip dependencies. Uses:
- `urllib.request` (stdlib) for CAS HTTP calls
- Existing `shared.*` modules (server, db, config, models)

### antlr4-python3-runtime Version Pin

The `antlr4-python3-runtime` package **must** be pinned to `4.11.1`. SymPy's `parse_latex()` ANTLR backend requires this exact version. Newer versions break the generated parser.

---

## 7. Open Items for Phase 15 (Implementation)

1. **CAS repo init**: `uv init cas-service`, configure pyproject.toml
2. **LaTeX → Maxima conversion**: The manual mapping table needs to be built during implementation. Start with common constructs (fractions, roots, trig, powers, subscripts).
3. **Equation detection**: How to detect `=` in LaTeX that's part of an equation vs. part of `\leq`, `\geq`, etc. Solution: split on `=` only when not preceded by `<`, `>`, `!`, `\`.
4. **Engine parallelism**: The CAS service runs engines sequentially in v1. Parallel execution (threading) can be added later if Maxima's 248ms becomes a bottleneck.
5. **Batch optimization**: The Validator service calls CAS once per formula. No batching in CAS service v1. If needed, add `POST /validate-batch` later.
