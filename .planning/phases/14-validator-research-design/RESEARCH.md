# Phase 14 Research: Validator Service

## CAS Microservice Analysis (N8N_dev :8769)

### Architecture
- **Location**: `/media/sam/1TB/N8N_dev/scripts/cas_microservice.py` (13KB)
- **Engines**: maxima, sagemath, matlab (via `cas` parameter)
- **API**: `POST /validate` with `{"latex": "...", "cas": "maxima"}`

### Engine Status (Live Test)

| Engine | Status | Root Cause | Fix |
|--------|--------|------------|-----|
| **Maxima** | Working (248ms) | `maxima_validator.py` calls Maxima subprocess | N/A |
| **SageMath** | BROKEN | Actually SymPy-based, needs `antlr4-python3-runtime==4.11.*` | `pip install antlr4-python3-runtime==4.11.1` |
| **Real SageMath** | BROKEN | Docker image `sagemath/sagemath` not present, 30s timeout | Out of scope (too heavy) |
| **MATLAB** | BROKEN | No MATLAB license/install | Out of scope |

### Key Finding
The "sagemath" engine in `cas_microservice.py` is **not real SageMath** — it's `sagemath_validator.py` which uses `sympy.parsing.latex.parse_latex()`. The name is misleading. The fix is a simple pip install of the antlr4 runtime.

There's also `real_sagemath_validator.py` that uses Docker `sagemath/sagemath` image — this is too heavy and unreliable (30s+ startup).

### CAS API Contract
```
POST http://localhost:8769/validate
Content-Type: application/json

{"latex": "x^2 + 2*x + 1", "cas": "maxima"}

Response:
{
  "success": true,
  "simplified": "x^2 + 2*x + 1",
  "engine": "maxima",
  "time_ms": 248
}
```

## SymPy LaTeX Parsing

### parse_latex API
```python
from sympy.parsing.latex import parse_latex
expr = parse_latex(r"\frac{1 + \sqrt{a}}{b}")
# Returns: (sqrt(a) + 1)/b
```

### Backends
- **ANTLR** (default): More lenient, may silently drop unparseable parts
- **Lark**: Stricter, raises exceptions on ill-formed input

### Supported Constructs
- Greek symbols, subscripts, fractions, roots, trig functions
- Integrals, derivatives, limits, sums, products
- Absolute values, factorials, binomials

### NOT Supported
- Matrices (bmatrix, pmatrix environments)
- Higher-order/partial derivatives (limited)
- Double/triple integrals
- Multi-character symbol names (need `\mathit{}`)

### Known Pitfalls
1. **Implicit multiplication**: `\eta \left(\sqrt{2-\eta^2}\right)` not recognized as multiplication
2. **Multi-char names**: `Nu`, `Re` treated as `N*u`, `R*e`
3. **Greek subscripts**: `\alpha_123` roundtrip broken in some versions
4. **Silent failures**: ANTLR may return partial parse without warning

### Equivalence Testing
- `==`: structural equality only (fast, limited)
- `.equals()`: numerical random-point testing (heuristic)
- `simplify(a - b) == 0`: symbolic (reliable, slow)

## LaTeX Preprocessing Pipeline

### Phase 1: Strip Environments
Remove `\begin{equation}...\end{equation}`, `\begin{align}`, etc.

### Phase 2: Remove Typographical Commands
`\left`, `\right`, `\displaystyle`, `\mathrm{...}`, `\text{...}`, spacing commands

### Phase 3: Normalize Synonyms
`\dfrac` → `\frac`, `\ge` → `\geq`, `\operatorname{sin}` → `\sin`

### Phase 4: Whitespace & Brackets
Collapse whitespace, remove redundant braces

### Phase 5: Parse to CAS
Try `parse_latex()`, catch errors, fallback to Lark backend

## Design Decision: Engine Selection

### Recommended for Validator v5.0

| Engine | Role | Integration |
|--------|------|-------------|
| **SymPy** (local) | Primary validator | `parse_latex()` + `simplify()` in-process |
| **Maxima** (CAS :8769) | Secondary validator | HTTP POST to existing microservice |
| **Wolfram Alpha** | Tertiary (optional) | API key needed, rate-limited |

### Consensus Logic
- 2 engines minimum (SymPy + Maxima)
- If both parse successfully: compare simplified forms
- If one fails: mark as "partial" validation, not "invalid"
- All-or-nothing: any engine **error** (not "invalid") → formula needs review

### Why NOT real SageMath
- Docker image is 5+ GB
- 30+ second startup time
- SymPy already provides equivalent symbolic computation
- Maxima provides independent verification

## Dependencies

### New (for Validator)
- `sympy` (already installed, but need `antlr4-python3-runtime==4.11.1` for parse_latex)
- No new pip packages needed beyond antlr4

### Existing (reused)
- `pydantic` (models)
- `requests` (for CAS :8769 HTTP calls, or stdlib urllib)
