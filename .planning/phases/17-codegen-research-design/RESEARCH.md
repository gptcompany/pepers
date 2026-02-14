# Research: Codegen Service (Phase 17)

## 1. SymPy Code Generation Pipeline

### Architecture (4 livelli)

```
LaTeX string
  → sympy.parsing.latex.parse_latex()  → SymPy Expression
  → Code Printers (ccode, rust_code, pycode)  → Code Strings
  → codegen() / RustCodeGen / CCodeGen  → Complete Files (.c/.h, .rs, .py)
  → autowrap() / lambdify()  → Callable Functions (not needed for our use case)
```

### LaTeX Parsing

```python
from sympy.parsing.latex import parse_latex
expr = parse_latex(r"\frac{p}{a} - \frac{q}{b}")  # → p/a - q/b
```

**Backends:**
- `antlr` (default): lenient, may silently fail on partial expressions
- `lark`: strict, rejects malformed LaTeX, customizable grammar

**Supported:** fractions, trig, integrals, sums, products, Greek letters, subscripts
**NOT supported (Lark):** matrices, partial derivatives, multiple integrals

**Security:** uses `eval` internally — do NOT pass unsanitized user input. Our formulas come from CAS-validated pipeline, so this is acceptable.

### Code Printers

| Language | Function | Status | Notes |
|----------|----------|--------|-------|
| C99 | `ccode(expr)` | Mature, first-class | `codegen("C99")` generates .c + .h |
| Rust | `rust_code(expr)` | Working, type bug fixed Aug 2024 | Known issue #26967 (integer promotion) |
| Python | `pycode(expr)` | Mature | Simple expression strings |

### C99 Code Generation (Primary Target)

```python
from sympy.utilities.codegen import codegen
from sympy.abc import p, q, a, b

expr = p/a - q/b
[(c_name, c_code), (h_name, c_header)] = codegen(
    ("kelly_fraction", expr), "C99", "kelly", header=False, empty=False
)
# Output: double kelly_fraction(double a, double b, double p, double q) { ... }
```

**Strengths:**
- First-class support in `codegen()` function
- Generates complete .c + .h files
- CSE optimization available
- C99 standard math functions (`expm1`, `log1p`) via `sympy.codegen.cfunctions`

### Rust Code Generation (Secondary Target)

```python
from sympy.printing.rust import rust_code
from sympy.utilities.codegen import codegen

# Expression-level
rust_code(expr)  # → "p/a - q/b"

# Full function
result, = codegen(("kelly_fraction", expr), "Rust", header=False, empty=False)
# Output: fn kelly_fraction(a: f64, b: f64, p: f64, q: f64) -> f64 { ... }
```

**Known issues (current as of SymPy 1.14):**
- Issue #26967: integer literals not promoted to f64 in some contexts
- Workaround: declare symbols with `integer=True` where needed
- Matrices not supported (need Symars or cgen)

### Python Code Generation

```python
from sympy.printing.pycode import pycode
pycode(expr)  # → "p/a - q/b"
```

### Limitations (ALL languages)

- Symbolic integrals without closed-form solutions
- Special functions (Bessel, elliptic) without stdlib equivalents
- Piecewise without default case
- Unevaluated Derivative, Integral, Sum objects
- Complex numbers in C (need `complex.h` / `cpow`)

For Kelly criterion formulas, these limitations are unlikely to be hit — the formulas are algebraic (fractions, logs, powers).

## 2. LLM Formula Explanation

### Prompt Design

**System prompt:**
```
You are a mathematical finance expert who explains formulas to practitioners.
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
}
```

### Ollama Configuration

```python
payload = {
    "model": "qwen3:8b",
    "prompt": user_prompt + " /no_think",  # Disable reasoning mode
    "system": EXPLANATION_SYSTEM_PROMPT,
    "format": FormulaExplanation.model_json_schema(),  # Schema enforcement
    "stream": False,
    "keep_alive": "10m",
    "options": {
        "temperature": 0.2,
        "num_predict": 500,
        "num_ctx": 4096,  # Default 2048 is too small
    },
}
```

**Key insights:**
- Qwen3-8B performs like Qwen2.5-14B on STEM benchmarks
- Use `/no_think` for explanation tasks (not solving) — saves 100-500+ tokens
- Ollama `format` parameter uses llama.cpp grammar constraints (token masking)
- Must ALSO include schema in system prompt (model doesn't see `format` as context)
- `num_predict=500` prevents truncated JSON

### Fallback Chain (Reversed from Analyzer)

| Priority | Provider | Rationale |
|----------|----------|-----------|
| 1 | Ollama qwen3:8b | Local, free, fast, good for 90%+ formulas |
| 2 | Gemini SDK | Better for complex multi-line formulas |
| 3 | Gemini CLI | Last resort |

Analyzer uses Gemini-first because 5-criteria scoring needs larger model nuance.
Explanation is more mechanical — Ollama handles it fine as primary.

### Token Budget (4096 context)

| Component | Tokens |
|-----------|--------|
| System prompt + schema | ~300 |
| Few-shot examples (2) | ~400 |
| User prompt | ~50 |
| LaTeX formula | ~50-150 |
| Context (200 chars) | ~60 |
| **Total input** | **~860-960** |
| Output JSON | ~200-350 |

### Structured Output

Ollama supports native JSON schema enforcement since v0.5 (Dec 2024).
Validate with Pydantic after: `FormulaExplanation.model_validate_json(response)`.

## 3. Service Architecture

### Module Structure

```
services/codegen/
    __init__.py
    main.py         # CodegenHandler, /process endpoint, DB ops
    explain.py      # LLM explanation (prompt, fallback chain)
    generators.py   # SymPy codegen (C99 + Rust + Python)
```

### Data Flow

```
Input: formula_id (from validated formulas, stage='validated')

1. Load formula from DB (latex, context, paper info)
2. parse_latex() → SymPy expression
3. LLM explanation → store in formulas.description
4. ccode() → C99 code → store in generated_code (language='c99')
5. rust_code() → Rust code → store in generated_code (language='rust')
6. pycode() → Python code → store in generated_code (language='python')
7. Update formula stage → 'codegen'
```

### Database (existing schema)

```sql
-- Already exists in shared/db.py
CREATE TABLE generated_code (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id INTEGER NOT NULL REFERENCES formulas(id),
    language TEXT NOT NULL,       -- 'c99', 'rust', 'python'
    code TEXT NOT NULL,           -- Generated code string
    metadata TEXT,                -- JSON: {function_name, variables, cse_applied}
    stage TEXT NOT NULL DEFAULT 'codegen',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Endpoints

- `POST /process` — Generate code for validated formulas
- `GET /health` — Health check
- `GET /status` — Service status + stats

### LLM Client Refactoring

The `call_ollama()`, `call_gemini_sdk()`, `call_gemini_cli()` functions from
`services/analyzer/llm.py` should be extracted to `shared/llm.py` since both
Analyzer and Codegen need them. Only parameter-level differences:
- Analyzer: `format: "json"` (simple mode)
- Codegen: `format: schema.model_json_schema()` (enforced mode)

### Error Handling

- `parse_latex()` failure → formula stays 'validated', error logged
- LLM explanation failure (all 3 providers) → codegen proceeds without explanation
- `ccode()` / `rust_code()` failure → log error in generated_code.error, continue with other languages
- Per-formula isolation (same as extractor) — one failure doesn't block batch

## 4. Dependencies

### New Dependencies
- `sympy` — already in venv (used by CAS service, version 1.14.0)
- `antlr4-python3-runtime==4.11` — required for parse_latex (ANTLR backend)

### Existing Dependencies (no change)
- `pydantic` — FormulaExplanation model
- `google-genai` — Gemini SDK fallback
- stdlib: `http.server`, `sqlite3`, `json`, `logging`, `urllib.request`

## 5. Key Decisions

| Decision | Rationale |
|----------|-----------|
| C99 as primary codegen target | Most mature SymPy support, `codegen("C99")` is first-class |
| Rust as secondary target | `rust_code()` works, type bug fixed, generates .rs files |
| Python always generated | Trivial via `pycode()`, useful for quick validation |
| parse_latex with ANTLR backend | More lenient, handles partial expressions gracefully |
| Ollama-first for explanation | Local/free, good enough for 90%+ of algebraic formulas |
| /no_think for qwen3 | Saves tokens, explanation doesn't need chain-of-thought |
| Extract LLM client to shared/ | DRY — both analyzer and codegen use same fallback pattern |
| CSE off by default | Kelly criterion formulas are simple, CSE overhead not justified |

## Sources

- [SymPy Code Generation docs](https://docs.sympy.org/latest/modules/codegen.html)
- [SymPy codegen() utility](https://docs.sympy.org/latest/modules/utilities/codegen.html)
- [SymPy Rust printer source](https://github.com/sympy/sympy/blob/master/sympy/printing/rust.py)
- [SymPy Rust type fix PR #26882](https://github.com/sympy/sympy/issues/25173)
- [SymPy parse_latex docs](https://docs.sympy.org/latest/modules/parsing.html)
- [Symars — SymPy to Rust with matrix support](https://github.com/Da1sypetals/Symars)
- [Qwen3 Technical Report](https://arxiv.org/abs/2505.09388)
- [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama Blog: Structured Outputs](https://ollama.com/blog/structured-outputs)
