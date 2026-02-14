# Design: Codegen Service (Phase 17)

## Overview

The Codegen service (port 8774) transforms CAS-validated formulas into multi-language code with LLM-generated explanations. It reads formulas with `stage='validated'`, generates code in three languages (C99, Rust, Python), produces a plain-language explanation via LLM, and stores results in the existing `generated_code` table.

**Service pattern**: Same as Validator (v5.0) — `BaseHandler` + `@route` + module structure.

## 1. LLM Client Refactoring (`shared/llm.py`)

### Problem

`services/analyzer/llm.py` contains 6 functions (210 LOC) that both Analyzer and Codegen need:
- `call_ollama()`, `call_gemini_sdk()`, `call_gemini_cli()`
- `fallback_chain()`
- `_get_gemini_api_key()`, `_strip_markdown_fences()`

### Solution

Extract to `shared/llm.py` with a configurable fallback order.

### API

```python
# shared/llm.py

def call_gemini_cli(prompt: str, system: str, model: str = "gemini-2.5-flash",
                    timeout: int = 120) -> str
def call_gemini_sdk(prompt: str, system: str, model: str = "gemini-2.5-flash",
                    timeout: float = 30.0) -> str
def call_ollama(prompt: str, system: str, model: str = "qwen3:8b",
                timeout: int = 120, base_url: str = "http://localhost:11434",
                format: str | dict = "json",
                options: dict | None = None) -> str

def fallback_chain(prompt: str, system: str,
                   order: list[str] | None = None) -> tuple[str, str]
    """
    order: ["gemini_cli", "gemini_sdk", "ollama"] (default, Analyzer)
           ["ollama", "gemini_sdk", "gemini_cli"] (Codegen)
    Returns: (response_text, provider_name)
    """
```

### Changes to `call_ollama()`

Add two new parameters vs current version:
- `format: str | dict = "json"` — supports both `"json"` (Analyzer) and `model_json_schema()` dict (Codegen structured output)
- `options: dict | None = None` — allows caller to set `num_ctx`, `num_predict`, `temperature`

Default `options` when None: `{"temperature": 0.3, "num_predict": 500}` (same as current).

### Changes to `fallback_chain()`

Add `order` parameter:
- Default `None` → `["gemini_cli", "gemini_sdk", "ollama"]` (backward compatible with Analyzer)
- Codegen passes `["ollama", "gemini_sdk", "gemini_cli"]`

### Migration

1. Create `shared/llm.py` with all 6 functions (enhanced)
2. Replace `services/analyzer/llm.py` body with re-exports:
   ```python
   # services/analyzer/llm.py — backward compat
   from shared.llm import (
       call_gemini_cli,
       call_gemini_sdk,
       call_ollama,
       fallback_chain,
   )
   ```
3. Analyzer tests continue to pass unchanged

## 2. Code Generation Module (`services/codegen/generators.py`)

### Module Structure

```python
# services/codegen/generators.py (~150 LOC)

from sympy.parsing.latex import parse_latex
from sympy.utilities.codegen import codegen
from sympy.printing.pycode import pycode
from sympy.printing.rust import rust_code

def parse_formula(latex: str) -> sympy.Expr
    """Parse LaTeX string to SymPy expression using ANTLR backend."""

def generate_c99(expr: sympy.Expr, func_name: str) -> dict
    """Generate C99 code via codegen("C99").
    Returns: {"code": str, "header": str, "variables": list[str]}"""

def generate_rust(expr: sympy.Expr, func_name: str) -> dict
    """Generate Rust code via codegen("Rust").
    Returns: {"code": str, "variables": list[str]}"""

def generate_python(expr: sympy.Expr, func_name: str) -> str
    """Generate Python expression via pycode().
    Returns: Python code string."""

def generate_all(latex: str, formula_id: int) -> list[dict]
    """Generate code in all 3 languages for a formula.
    Returns: list of {language, code, metadata, error} dicts."""
```

### `parse_formula()`

```python
def parse_formula(latex: str) -> sympy.Expr:
    """Parse LaTeX to SymPy expression.

    Uses ANTLR backend (default, more lenient).
    Strips environment wrappers (\\begin{equation}...\\end{equation}).
    """
    # Strip LaTeX environments
    cleaned = re.sub(r'\\begin\{[^}]+\}|\\end\{[^}]+\}', '', latex).strip()
    return parse_latex(cleaned)
```

### `generate_c99()`

```python
def generate_c99(expr: sympy.Expr, func_name: str) -> dict:
    """Generate complete C99 function via SymPy codegen.

    Returns:
        {"code": "double func(double a, ...) { ... }",
         "header": "#include ...\ndouble func(double a, ...);",
         "variables": ["a", "b", "p"]}
    """
    variables = sorted(expr.free_symbols, key=str)
    [(c_name, c_code), (h_name, c_header)] = codegen(
        (func_name, expr), "C99", func_name, header=False, empty=False
    )
    return {
        "code": c_code,
        "header": c_header,
        "variables": [str(v) for v in variables],
    }
```

### `generate_rust()`

```python
def generate_rust(expr: sympy.Expr, func_name: str) -> dict:
    """Generate Rust function via SymPy codegen.

    Known issue: integer literals may not be promoted to f64 (#26967).
    Post-process: replace bare integer literals with f64 casts.
    """
    variables = sorted(expr.free_symbols, key=str)
    [(rs_name, rs_code)] = codegen(
        (func_name, expr), "Rust", func_name, header=False, empty=False
    )
    return {
        "code": rs_code,
        "variables": [str(v) for v in variables],
    }
```

### `generate_python()`

```python
def generate_python(expr: sympy.Expr, func_name: str) -> str:
    """Generate Python expression via pycode().

    Returns a simple expression string (no function wrapper).
    """
    return pycode(expr)
```

### `generate_all()`

```python
def generate_all(latex: str, formula_id: int) -> list[dict]:
    """Generate code in all languages. Per-language error isolation."""
    func_name = f"formula_{formula_id}"

    try:
        expr = parse_formula(latex)
    except Exception as e:
        return [{"language": lang, "code": "", "metadata": None,
                 "error": f"parse_latex: {e}"}
                for lang in ("c99", "rust", "python")]

    results = []
    for lang, gen_func in [("c99", generate_c99), ("rust", generate_rust)]:
        try:
            result = gen_func(expr, func_name)
            results.append({
                "language": lang,
                "code": result["code"],
                "metadata": {"function_name": func_name,
                             "variables": result["variables"]},
                "error": None,
            })
        except Exception as e:
            results.append({"language": lang, "code": "", "metadata": None,
                            "error": str(e)})

    # Python always succeeds if parse succeeded
    try:
        py_code = generate_python(expr, func_name)
        results.append({
            "language": "python",
            "code": py_code,
            "metadata": {"function_name": func_name,
                          "variables": [str(s) for s in sorted(expr.free_symbols, key=str)]},
            "error": None,
        })
    except Exception as e:
        results.append({"language": "python", "code": "", "metadata": None,
                        "error": str(e)})

    return results
```

### Function Naming

Formula ID → function name: `formula_{id}` (e.g., `formula_42`).
Simple, deterministic, no name collisions.

## 3. LLM Explanation Module (`services/codegen/explain.py`)

### Module Structure

```python
# services/codegen/explain.py (~100 LOC)

from shared.llm import fallback_chain, call_ollama

EXPLANATION_SYSTEM_PROMPT: str  # Defined below
CODEGEN_FALLBACK_ORDER: list[str] = ["ollama", "gemini_sdk", "gemini_cli"]

def explain_formula(latex: str, context: str | None,
                    paper_title: str | None) -> dict | None
    """Generate plain-language explanation via LLM.
    Returns: FormulaExplanation dict or None on failure."""
```

### System Prompt

```python
EXPLANATION_SYSTEM_PROMPT = """You are a mathematical finance expert who explains formulas to practitioners.
Given a LaTeX formula and its surrounding context from an academic paper,
produce a plain-language explanation.

Rules:
1. Explain what the formula COMPUTES (purpose), not how to derive it
2. Define every variable/symbol used
3. State the key assumptions the formula requires
4. Use concrete financial examples when possible
5. Keep the explanation accessible to someone with undergraduate math

Respond ONLY with valid JSON matching this schema:
{
  "explanation": "<2-4 sentence plain-language explanation>",
  "variables": [{"symbol": "...", "name": "...", "description": "..."}],
  "assumptions": ["..."],
  "domain": "<mathematical finance | probability | optimization | statistics>"
}"""
```

### `explain_formula()`

```python
def explain_formula(latex: str, context: str | None,
                    paper_title: str | None) -> dict | None:
    """Generate explanation. Returns parsed JSON dict or None."""
    user_prompt = f"Formula: {latex}"
    if context:
        user_prompt += f"\nContext: {context}"
    if paper_title:
        user_prompt += f"\nPaper: {paper_title}"
    user_prompt += " /no_think"

    try:
        # Try Ollama first with structured output
        result = call_ollama(
            prompt=user_prompt,
            system=EXPLANATION_SYSTEM_PROMPT,
            format=FormulaExplanation.model_json_schema(),
            options={"temperature": 0.2, "num_predict": 500, "num_ctx": 4096},
        )
        return FormulaExplanation.model_validate_json(result).model_dump()
    except Exception:
        pass

    try:
        # Fallback to Gemini
        result, provider = fallback_chain(
            prompt=user_prompt,
            system=EXPLANATION_SYSTEM_PROMPT,
            order=["gemini_sdk", "gemini_cli"],
        )
        return FormulaExplanation.model_validate_json(result).model_dump()
    except Exception:
        return None
```

### FormulaExplanation Pydantic Model

Added to `shared/models.py`:

```python
class FormulaExplanation(BaseModel):
    """LLM-generated explanation of a validated formula.

    Populated by Codegen service. Stored as JSON in formulas.description.
    """

    explanation: str
    variables: list[dict[str, str]] = []
    assumptions: list[str] = []
    domain: str = ""
```

This is a validation-only model (no DB mapping needed) — the explanation JSON is stored in `formulas.description`.

## 4. Service Handler (`services/codegen/main.py`)

### File Structure

```
services/codegen/
    __init__.py       # empty
    main.py           # CodegenHandler + DB ops + main() (~250 LOC)
    generators.py     # SymPy code generation (~150 LOC)
    explain.py        # LLM explanation (~100 LOC)
```

### CodegenHandler

```python
class CodegenHandler(BaseHandler):
    """Handler for the Codegen service."""

    ollama_url: str = "http://localhost:11434"
    max_formulas_default: int = 50

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict | None:
        """Generate code for validated formulas."""
```

### API Contract

**Request** `POST /process`:
```json
{
    "paper_id": 123,
    "formula_id": 456,
    "max_formulas": 50,
    "force": false
}
```

All fields optional. Without `paper_id`/`formula_id`, processes all `stage='validated'` formulas up to `max_formulas`.

**Response** (success):
```json
{
    "success": true,
    "service": "codegen",
    "formulas_processed": 5,
    "code_generated": {
        "c99": 5,
        "rust": 4,
        "python": 5
    },
    "explanations_generated": 5,
    "errors": ["formula 12: parse_latex failed: unexpected token"],
    "time_ms": 8432
}
```

### Processing Pipeline (per formula)

```
1. Load formula row (id, latex, context, paper_id)
2. Load paper title (JOIN papers ON id = formula.paper_id)
3. explain_formula(latex, context, paper_title) → description JSON
4. Store explanation in formulas.description
5. generate_all(latex, formula_id) → [{language, code, metadata, error}, ...]
6. Store each in generated_code table
7. Update formula stage: 'validated' → 'codegen'
8. On any unrecoverable error: mark formula 'failed'
```

### DB Operations

```python
def _query_formulas(db_path, paper_id, formula_id, max_formulas, force) -> list[dict]:
    """Query formulas ready for codegen (stage='validated').
    With force=True, also re-process 'codegen' stage formulas.
    JOINs papers table to get paper title for explanations."""

def _store_generated_code(db_path, formula_id, language, code, metadata, error) -> None:
    """INSERT into generated_code. DELETE existing for same formula+language first."""

def _update_formula_description(db_path, formula_id, description_json) -> None:
    """UPDATE formulas SET description = ? WHERE id = ?"""

def _update_formula_stage(db_path, formula_id) -> None:
    """UPDATE formulas SET stage = 'codegen' WHERE id = ?"""

def _mark_formula_failed(db_path, formula_id, error) -> None:
    """UPDATE formulas SET stage = 'failed', error = ? WHERE id = ?"""
```

### Configuration

```bash
RP_CODEGEN_PORT=8774                       # Service port
RP_CODEGEN_OLLAMA_URL=http://localhost:11434  # Ollama base URL
RP_CODEGEN_MAX_FORMULAS=50                 # Default batch size
RP_DB_PATH=data/research.db               # SQLite database path
RP_LOG_LEVEL=INFO                          # Log level
```

### `main()`

```python
def main() -> None:
    config = load_config("codegen")
    init_db(config.db_path)

    CodegenHandler.ollama_url = os.environ.get(
        "RP_CODEGEN_OLLAMA_URL", "http://localhost:11434"
    )
    CodegenHandler.max_formulas_default = int(
        os.environ.get("RP_CODEGEN_MAX_FORMULAS", "50")
    )

    service = BaseService(
        "codegen", config.port, CodegenHandler, str(config.db_path)
    )
    service.run()
```

## 5. Schema & Model Updates

### No Schema Migration Needed

The `generated_code` table already exists in `shared/db.py` SCHEMA with the correct columns:
- `formula_id`, `language`, `code`, `metadata`, `stage`, `error`, `created_at`
- Index `idx_generated_code_formula_id` already exists

### `formulas.description` Column

Already exists in schema. Currently NULL for all formulas. Codegen stores the explanation JSON here:
```json
{
    "explanation": "The Kelly fraction ...",
    "variables": [{"symbol": "p", "name": "probability of win", "description": "..."}],
    "assumptions": ["Independent trials", "Known probabilities"],
    "domain": "mathematical finance"
}
```

### New Pydantic Model

Add `FormulaExplanation` to `shared/models.py` (validation-only, no DB table):

```python
class FormulaExplanation(BaseModel):
    """LLM-generated explanation of a validated formula."""

    explanation: str
    variables: list[dict[str, str]] = []
    assumptions: list[str] = []
    domain: str = ""
```

### Metadata JSON Structure

`generated_code.metadata` stores:
```json
{
    "function_name": "formula_42",
    "variables": ["a", "b", "p", "q"],
    "parse_backend": "antlr"
}
```

## 6. Error Handling Matrix

| Error | Impact | Action | Formula Stage |
|-------|--------|--------|---------------|
| `parse_latex()` fails | All 3 languages fail | Log, store error in all generated_code rows | `failed` |
| `codegen("C99")` fails | C99 only | Store error for C99, continue Rust/Python | `codegen` (partial) |
| `codegen("Rust")` fails | Rust only | Store error for Rust, continue Python | `codegen` (partial) |
| `pycode()` fails | Python only | Store error for Python | `codegen` (partial) |
| LLM explanation fails (all providers) | No description | Continue with codegen (description = NULL) | `codegen` |
| Empty LaTeX | All | Skip formula, log warning | unchanged |
| DB write fails | Critical | Re-raise, abort current formula | `failed` |

### Per-Language Isolation

If C99 fails but Rust and Python succeed, the formula still gets `stage='codegen'` and the successful code is stored. The C99 `generated_code` row gets `error` populated.

### Explanation is Optional

If all LLM providers fail, codegen proceeds without explanation. `formulas.description` stays NULL. This is acceptable — the code is the primary deliverable.

## 7. Dependencies

### New Dependencies (Phase 18)

| Dependency | Version | Usage | Notes |
|------------|---------|-------|-------|
| `sympy` | 1.14.0 | Code generation | Already in venv |
| `antlr4-python3-runtime` | 4.11.* | `parse_latex()` ANTLR backend | Must pin to 4.11 |

### Verification

```bash
python -c "from sympy.parsing.latex import parse_latex; print(parse_latex(r'\frac{1}{2}'))"
# Expected: 1/2
```

If `antlr4-python3-runtime` not installed or wrong version:
```bash
pip install "antlr4-python3-runtime>=4.11,<4.12"
```

## 8. Data Flow Diagram

```
formulas (stage='validated')
    │
    ├─── explain_formula(latex, context, title)
    │         │
    │         ├── call_ollama(format=schema) ──→ FormulaExplanation JSON
    │         ├── call_gemini_sdk() ──→ fallback
    │         └── call_gemini_cli() ──→ fallback
    │         │
    │         └──→ UPDATE formulas.description
    │
    ├─── generate_all(latex, formula_id)
    │         │
    │         ├── parse_formula(latex) ──→ SymPy Expr
    │         │
    │         ├── generate_c99(expr, name)
    │         │     └──→ INSERT generated_code (language='c99')
    │         │
    │         ├── generate_rust(expr, name)
    │         │     └──→ INSERT generated_code (language='rust')
    │         │
    │         └── generate_python(expr, name)
    │               └──→ INSERT generated_code (language='python')
    │
    └──→ UPDATE formulas.stage = 'codegen'
```

## 9. Phase 18 Implementation Order

1. **shared/llm.py** — Extract from analyzer/llm.py, add `format`/`options` params, add `order` to `fallback_chain`
2. **Update analyzer/llm.py** — Re-export from shared/llm (backward compat)
3. **shared/models.py** — Add `FormulaExplanation` model
4. **services/codegen/__init__.py** — Empty
5. **services/codegen/generators.py** — SymPy code generation
6. **services/codegen/explain.py** — LLM explanation
7. **services/codegen/main.py** — CodegenHandler + DB ops + main()
8. **Verify** — Run existing tests (no regressions), manual test with sample LaTeX
