# Phase 14 Context: Validator Service Research & Design

## Phase Goal
Design the Validator service architecture and a standalone CAS microservice (separate repo), including LaTeX preprocessing, multi-engine validation, consensus logic, and validation reporting.

## Key Decisions

### CAS Architecture: Separate Microservice (User Decision)
- **NOT** using N8N_dev CAS microservice — create new standalone repo
- New repo: `cas-service` (or similar) — completely isolated
- Validator service calls CAS service via HTTP
- CAS service manages SymPy + Maxima engines internally

### Validation Engines
1. **SymPy** (Python, in-process within CAS service): `parse_latex()` + `simplify()`
2. **Maxima** (subprocess within CAS service): Maxima CLI for algebraic verification
3. **Wolfram Alpha**: Out of scope for v5.0 (requires API key, rate-limited)

### Consensus Logic
- 2 engines: SymPy + Maxima
- Both parse OK + agree → formula VALID
- Both parse OK + disagree → formula INVALID (needs review)
- One engine errors → "partial" validation (not conclusive)
- Both error → formula UNPARSEABLE (skip, not failed)

## What Validator Service Does
1. Read formulas from DB where `stage='extracted'`
2. For each formula:
   a. Preprocess LaTeX (strip environments, normalize commands)
   b. Send to CAS service for validation (SymPy + Maxima)
   c. Receive per-engine results
   d. Apply consensus logic
   e. Store `Validation` records (one per engine)
   f. Update formula stage to 'validated' or 'failed'
3. Return summary

## What CAS Service Does (new repo)
1. Accept `POST /validate` with `{"latex": "...", "engines": ["sympy", "maxima"]}`
2. Preprocess LaTeX for each engine
3. Run validation in parallel (SymPy in-process, Maxima subprocess)
4. Return per-engine results
5. Expose `/health`, `/status`, `/engines` endpoints

## Constraints from User
- CAS service in separate repo, completely isolated from N8N_dev
- Validator at port 8773 (per existing architecture)
- CAS service at port 8769 (reuse existing port assignment)
- KISS: stdlib http.server pattern for both services
- No Docker for SageMath (too heavy)
- No Wolfram Alpha (out of scope)

## Technical Findings (from Research)

### LaTeX Preprocessing Required
Before CAS engines can parse formulas:
1. Strip math environments (`\begin{equation}`, etc.)
2. Remove typographical commands (`\left`, `\right`, `\displaystyle`, fonts)
3. Normalize synonyms (`\dfrac` → `\frac`)
4. Collapse whitespace

### SymPy parse_latex Limitations
- Needs `antlr4-python3-runtime==4.11.1`
- No matrix support
- Silent partial parse failures possible
- Implicit multiplication ambiguous

### Maxima Integration
- Maxima installed on Workstation via apt
- Called via subprocess: `echo "tex(simplify(latex_expr));" | maxima --very-quiet`
- 248ms typical response time

## Dependencies (New)
- `sympy` (already in project deps)
- `antlr4-python3-runtime==4.11.1` (new, for parse_latex)
- `maxima` system package (already installed)

## Open Questions
- CAS service repo name? (e.g., `cas-service`, `formula-validator-cas`)
- Should CAS service share the research-pipeline SQLite DB? → NO, CAS is stateless
- Schema changes needed? → NO, existing `validations` table sufficient
