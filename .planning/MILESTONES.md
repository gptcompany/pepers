# Project Milestones: Research Pipeline

## v6.0 Codegen Service (Shipped: 2026-02-14)

**Delivered:** LLM-powered plain-language formula explanation + multi-language code generation (C99/Rust/Python via SymPy) — completing the pipeline from validated math to production code.

**Phases completed:** 17-19 (3 plans total)

**Key accomplishments:**

- LLM client refactoring: shared/llm.py (239 LOC) with configurable fallback order (Ollama-first or Gemini-first)
- SymPy code generation: C99, Rust, Python via `codegen()` + `pycode()` with per-language error isolation
- LLM explanation: plain-language formula explanation via Ollama structured output + Gemini fallback
- Codegen service handler: /process endpoint with 5 DB operations, stage management (validated→codegen)
- Full test suite: 69 new tests (39 unit + 20 integration + 10 e2e), 86% coverage
- E2E validated: real SymPy + real Ollama confirmed working end-to-end

**Stats:**

- 23 files changed, 3,253 insertions
- 806 LOC production + 960 LOC tests = 1,766 LOC total
- 3 phases, 3 plans
- 4 days (2026-02-10 → 2026-02-14)

**Git range:** `5f03a10` → `04ee780`

**What's next:** v7.0 — Orchestrator + Deploy (systemd, monitoring, Discord notifications)

---

## v5.0 Validator Service (Shipped: 2026-02-14)

**Delivered:** Multi-CAS formula validation with all-or-nothing consensus — new standalone CAS microservice (SymPy + Maxima + MATLAB) and Validator service that dispatches, scores consensus, and writes results to SQLite.

**Phases completed:** 14-16 (4 plans total)

**Key accomplishments:**

- CAS microservice: standalone repo, SymPy 1.14.0 + Maxima 5.45.1 + MATLAB (license temp. unavailable), 4-phase LaTeX preprocessing
- Validator service: consensus logic (VALID/INVALID/PARTIAL/UNPARSEABLE), CAS client, DB integration
- Comprehensive design: 34K LOC DESIGN.md with API contracts and decision matrix
- 56 new tests (30 unit + 18 integration + 8 E2E), 87% coverage, real CAS E2E validation
- All 363 tests pass, zero regressions

**Stats:**

- 22 files changed, 3,394 insertions
- 492 LOC service + 990 LOC tests = 1,482 LOC (research-pipeline)
- 698 LOC CAS microservice (separate repo)
- 3 phases, 4 plans
- 1 day (2026-02-13 → 2026-02-14)

**Git range:** `4545b73` → `1edd27e`

**What's next:** v6.0 — Codegen Service (Python/Rust code generation from validated formulas)

---

## v4.0 Extractor Service (Shipped: 2026-02-13)

**Delivered:** Third microservice — downloads PDFs from arXiv, sends to RAGAnything for text extraction, parses LaTeX formulas via 5-pass regex engine with occupied-span tracking, and stores formulas with context in SQLite.

**Phases completed:** 11-13 (3 plans total)

**Key accomplishments:**

- RAGAnything API research + N8N W3 workflow analysis with 4 parallel agents
- arXiv PDF download with `requests` retry strategy and local caching
- RAGAnything HTTP client with async polling and container→host path mapping
- 5-pass LaTeX regex engine with occupied-span tracking (equation, align, \[...\], $$...$$, $...$)
- Formula filtering (hash dedup, min length, LaTeX command check) and context extraction
- 60 new tests (47 unit, 13 integration, 3 E2E), 94% coverage

**Stats:**

- 21 files changed, 3,379 insertions
- 644 LOC service + 999 LOC tests = 1,643 total
- 3 phases, 3 plans
- 1 day (2026-02-13)

**Git range:** `8f395f8` → `2bed979`

**What's next:** v5.0 — Validator Service (Multi-CAS consensus scoring)

---

## v3.0 Analyzer Service (Shipped: 2026-02-13)

**Delivered:** LLM-based relevance scoring with triple fallback (Gemini CLI → SDK → Ollama) that filters discovered papers on 5 criteria before expensive downstream processing.

**Phases completed:** 8-10 (3 plans total)

**Key accomplishments:**

- Gemini CLI/SDK and Ollama API research with fallback chain design
- 5-criteria scoring prompt (kelly_relevance, mathematical_rigor, novelty, practical_applicability, data_quality)
- Triple LLM fallback: Gemini CLI → Gemini SDK → Ollama qwen3:8b
- Score threshold 0.7 with REJECTED stage for deliberate filtering
- Schema migration (prompt_version column) for prompt versioning
- 77 new tests (60 unit, 14 integration, 3 E2E with real Ollama), 91% coverage

**Stats:**

- 24 files changed, 3,673 insertions
- 600 LOC service + 1,301 LOC tests = 1,901 total
- 3 phases, 3 plans
- 1 day (2026-02-12 → 2026-02-13)

**Git range:** `40ccf90` → `3920a9a`

**What's next:** v4.0 — Extractor Service (RAGAnything + LaTeX formula extraction)

---

## v2.0 Discovery Service (Shipped: 2026-02-12)

**Delivered:** First microservice — fetches arXiv papers by keywords, enriches with Semantic Scholar and CrossRef metadata, stores in SQLite DB.

**Phases completed:** 5-7 (3 plans total)

**Key accomplishments:**

- arXiv API integration with query syntax and rate limiting
- Semantic Scholar v2 API enrichment (citations, fields of study, TLDR)
- CrossRef REST API for DOI metadata
- Discovery HTTP handler with /process endpoint
- Unit + integration + E2E test suite with real API calls

**Stats:**

- 448 LOC service code
- 3 phases, 3 plans
- 2 days (2026-02-10 → 2026-02-12)

**Git range:** `e3b3ba1` → `575fb7e`

**What's next:** v3.0 — Analyzer Service

---

## v1.0 Foundation (Shipped: 2026-02-10)

**Delivered:** Shared infrastructure library (DB layer, Pydantic models, base HTTP server, config management) that all 5 microservices + orchestrator will depend on.

**Phases completed:** 1-4 (4 plans total)

**Key accomplishments:**

- CAS microservice analysis + shared lib architecture design with comprehensive ARCHITECTURE.md
- SQLite DB layer with 5 tables, 6 indexes, WAL mode, idempotent schema init
- 8 Pydantic models with JSON field validators for SQLite TEXT round-trips
- Base HTTP server with @route decorator dispatch, JSON logging, SIGTERM handling
- 103 tests with 98% coverage, 0 type errors

**Stats:**

- 36 files created
- ~2091 lines of Python
- 4 phases, 4 plans
- 1 day (2026-02-10)

**Git range:** `3ee2602` → `e3b3ba1`

**What's next:** v2.0 — First microservice implementations (Discovery, Analyzer, etc.)

---
