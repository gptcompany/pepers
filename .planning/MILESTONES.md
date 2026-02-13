# Project Milestones: Research Pipeline

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
