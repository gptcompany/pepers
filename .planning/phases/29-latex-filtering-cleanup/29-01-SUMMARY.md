# Summary 29-01: LaTeX Filtering + Cleanup

## Result: COMPLETE

## Changes Made

### Bug 1: MIN_FORMULA_LENGTH too permissive (MEDIUM → FIXED)
- **File**: `services/extractor/latex.py` (+79 LOC)
- Raised `MIN_FORMULA_LENGTH` from 3 to 10
- Added `is_nontrivial()` complexity heuristic:
  - Rejects single greek letters (`\mu`, `\sigma`, `\alpha_t`)
  - Rejects pure superscript/subscript fragments (`^{1}`, `_{i}`)
  - Accepts formulas with arithmetic operators (`+`, `-`, `=`) regardless of length
  - Accepts formulas with LaTeX operators (`\frac`, `\sum`, `\int`, etc.)
  - Accepts formulas with 2+ meaningful LaTeX commands
- Updated `filter_formulas()` to use `is_nontrivial()` — short formulas with operators still pass

### Bug 2: codegen doesn't strip LaTeX macros (MEDIUM → FIXED)
- **File**: `services/codegen/generators.py` (+43 LOC)
- Added `clean_latex()` function that strips 9 categories of unsupported macros:
  1. Annotations: `\tag{N}`, `\label{eq:1}`
  2. Text/formatting: `\text{}`, `\mathrm{}`, `\pmb{}`, `\operatorname{}`, etc. (unwraps content)
  3. Spacing: `\,`, `\;`, `\quad`, `\qquad`
  4. Delimiters: `\left`, `\right`
  5. Equivalence: `\equiv` → `=`, `\triangleq` → `=`
  6. Dots: `\dots`, `\cdots`, `\ldots`
  7. Style: `\displaystyle`, `\textstyle`
  8. Alignment: `\\` → space, `&` → space, `\nonumber`, `\notag`
  9. Whitespace collapse
- Integrated into `parse_formula()` after existing env/delimiter stripping

### Bug 3: ~35% parse failure rate (MEDIUM → MITIGATED)
- Root cause: Bugs 1 + 2 combined
- Trivial fragments inflated failure count (now filtered out)
- Unsupported macros caused unnecessary parse failures (now cleaned)
- Actual parse failure rate will be measured in Phase 30 regression tests

### Tests Added
- **`tests/unit/test_extractor.py`**: +14 tests
  - `TestIsNontrivial`: 11 tests (operators, greek, scripts, commands)
  - `TestFilterFormulas`: +7 tests (greek rejection, script rejection, operator acceptance, length)
- **`tests/unit/test_codegen.py`**: +20 tests
  - `TestCleanLatex`: 16 tests (tag, label, text, mathrm, pmb, spacing, left/right, equiv, dots, displaystyle, alignment, preservation)
  - `TestParseFormula`: +4 integration tests (tag, displaystyle, equiv, left/right)

## Metrics

| Metric | Value |
|--------|-------|
| Files changed | 4 |
| LOC added | 333 |
| LOC removed | 8 |
| Tests passed | 582/582 |
| New tests | 34 |
| Type errors (modified files) | 0 |
| Ruff errors (modified files) | 0 |
| Confidence gate (plan) | 95% AUTO_APPROVE |
| Confidence gate (impl) | 95% AUTO_APPROVE |

## Acceptance Criteria

- [x] `\mu`, `\sigma`, `^{1}` rejected by `filter_formulas()`
- [x] `\frac{a}{b}`, `\sum_{i=1}^{n} x_i` still accepted
- [x] `\tag{13}` stripped before parse_latex()
- [x] `\text{profit}` unwrapped before parse_latex()
- [x] `\equiv` replaced with `=`
- [x] All existing tests pass (582)
- [x] New unit tests pass for both modules
- [x] 0 type errors in modified files
