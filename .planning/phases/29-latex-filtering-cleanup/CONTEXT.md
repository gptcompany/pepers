# Context: Phase 29 — LaTeX Filtering + Cleanup

## Phase Goal

Add complexity filter to reject trivial LaTeX fragments, clean up LaTeX macros before parse_latex() to prevent codegen misinterpretation, and reduce ~35% parse failure rate from unsupported LaTeX macros.

## Bugs to Fix

### Bug 1: MIN_FORMULA_LENGTH=3 allows trivial fragments (MEDIUM)

**File**: `services/extractor/latex.py:28,115-139`

**Problem**: `filter_formulas()` uses `MIN_FORMULA_LENGTH=3` which passes fragments like `^{1}`, `\mu`, `\sigma`, `\beta_t` — these are individual symbols, not real formulas. The E2E test on paper 15 (1806.05293) extracted 104 formulas, many spurious.

**Current filter** (line 120-129):
1. Skip if `len(latex.strip()) < 3`
2. Skip if no `\` and no `{` in latex
3. Deduplicate by hash

**Fix needed**: Add complexity heuristics beyond raw length:
- Require at least one operator (`+`, `-`, `=`, `\frac`, `\sum`, `\int`, `\prod`, `\partial`, `\cdot`, `\times`, `\leq`, `\geq`, `\neq`, `\approx`)
- OR require at least 2 distinct symbols/variables
- Raise MIN_FORMULA_LENGTH to ~10 characters
- Reject single-symbol formulas (`\mu`, `\sigma`, `\alpha`, etc.)

### Bug 2: codegen doesn't strip LaTeX macros before parse_latex() (MEDIUM)

**File**: `services/codegen/generators.py:25-46`

**Problem**: `parse_formula()` only strips `\begin{...}`, `\end{...}`, and `$$`/`$` delimiters. It does NOT clean up:
- `\tag{N}` → SymPy tries to interpret as function `tag(N)`
- `\label{...}` → same issue
- `\text{...}` → fails parsing
- `\pmb{...}` → undefined in SymPy
- `\dots`, `\cdots`, `\ldots` → no SymPy equivalent
- `\equiv` → not handled (should be `=`)
- `\triangleq` → not handled
- `\left`, `\right` → should be stripped (SymPy handles parens natively)
- `\,`, `\;`, `\:`, `\!`, `\quad`, `\qquad` → spacing commands, strip
- `\boldsymbol{...}`, `\mathbf{...}`, `\mathrm{...}`, `\mathbb{...}`, `\mathcal{...}` → unwrap to content
- `\operatorname{...}` → unwrap to content

### Bug 3: ~35% parse failure rate from unsupported macros (MEDIUM)

**Root cause**: Bugs 1 and 2 combined. Trivial fragments that can't be parsed inflate the failure rate, and complex formulas with unsupported macros fail unnecessarily because they could succeed after cleanup.

**Fix approach**: Pre-validation step before `parse_latex()`:
1. Clean up known macros (Bug 2 fix)
2. Try parse_latex()
3. If fails → mark as unparseable (don't retry)

## Files to Modify

| File | Changes |
|------|---------|
| `services/extractor/latex.py` | Add complexity heuristics to `filter_formulas()`, raise MIN_FORMULA_LENGTH |
| `services/codegen/generators.py` | Add `clean_latex()` function before `parse_latex()` in `parse_formula()` |

## Existing Test Files

| File | Purpose |
|------|---------|
| `tests/unit/test_extractor.py` | Unit tests for extractor, includes `filter_formulas` |
| `tests/unit/test_codegen.py` | Unit tests for codegen generators |
| `tests/integration/test_extractor_db.py` | Integration tests with DB |
| `tests/integration/test_codegen_db.py` | Integration tests with DB |
| `tests/e2e/test_extractor_e2e.py` | E2E tests with real PDFs |
| `tests/e2e/test_codegen_e2e.py` | E2E tests with real formulas |

## Scope

- 2 files modified, ~80-100 LOC added
- Tests: Phase 30 will handle regression tests
- No new dependencies
- No API changes — internal filter/cleanup only
