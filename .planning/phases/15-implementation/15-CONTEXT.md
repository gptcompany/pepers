# Phase 15 Context: Validator + CAS Implementation

## Phase Goal
Implement both the CAS microservice (separate repo) and the Validator service based on the Phase 14 DESIGN.md specification.

## Key References
- **DESIGN.md**: `.planning/phases/14-validator-research-design/DESIGN.md` (1072 lines)
- **Existing service pattern**: `services/extractor/` (handler + modules)
- **Shared library**: `shared/` (server.py, db.py, config.py, models.py)

## Two Deliverables

### 1. CAS Microservice (`/media/sam/1TB/cas-service/`)
- Separate repo, port 8769
- `POST /validate` with SymPy + Maxima engines
- LaTeX preprocessing pipeline
- Standalone — does NOT import from research-pipeline

### 2. Validator Service (`services/validator/`)
- Port 8773, uses shared/* library
- `POST /process` — reads formulas, calls CAS, writes validations
- CAS HTTP client (urllib.request)
- Consensus logic module

## Constraints
- CAS service uses stdlib `http.server` (same KISS pattern, but not shared.server)
- Validator uses shared.server.BaseHandler + @route
- No new pip deps in research-pipeline (stdlib urllib for HTTP)
- CAS service needs: sympy, antlr4-python3-runtime==4.11.1
- Maxima binary at /usr/bin/maxima (already installed)
