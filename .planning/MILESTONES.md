# Project Milestones: PePeRS

## v12.0 Distribution & Branding (Shipped: 2026-02-20)

**Delivered:** Project identity (PePeRS branding), MCP Server SSE with 8 tools and arcade flavor, RAGAnything context_only mode, one-click Docker/uv install, and OpenAlex multi-source discovery (200M+ works).

**Phases completed:** 38-42 (5 plans total)

**Key accomplishments:**

- PePeRS branding: project renamed across 19 files, professional README with logo
- RAGAnything context_only mode: chunk retrieval <2s (vs 60-90s with LLM synthesis)
- MCP Server SSE: 8 tools on :8776 with SEXY BAR ARCADE flavor (Metal Slug style)
- One-click install: Docker compose (pipeline + MCP) + `uv tool install pepers` + `pepers-mcp` CLI
- OpenAlex discovery: 200M+ works API client, schema v5 (source + openalex_id), cross-source dedup
- Adapter pattern: RP_DISCOVERY_SOURCES=arxiv,openalex env var for N-source configuration

**Stats:**

- 42 files changed, 3,599 insertions, 199 deletions
- ~3,400 LOC added (production + tests)
- 5 phases, 5 plans
- 2 days (2026-02-19 to 2026-02-20)

**Git range:** `a802eb9` → `00ae823`

**What's next:** Next milestone TBD — possible directions: production hardening II, monitoring, user feedback

---

## v9.0 Pipeline Hardening (Shipped: 2026-02-16)

**Delivered:** Fixed 6 bugs found during E2E pipeline test — stage transitions, batch overflow, LaTeX filtering, macro cleanup — plus 22 regression tests verifying all fixes.

**Phases completed:** 28-30 (3 plans total)

**Key accomplishments:**

- Stage transition fixes: validator and codegen now UPDATE papers.stage after processing
- Batch iteration loop in orchestrator: processes >50 formulas via repeated calls (safety cap 100)
- is_nontrivial() heuristic: rejects trivial LaTeX fragments (\alpha, ^{1}, \mu)
- clean_latex(): strips 9 categories of unsupported macros before parse_latex()
- 22 regression tests (18 integration + 4 E2E) covering all fixes with failure scenarios
- OpenRouter/Ollama max_tokens fixed (500 → 4096)

**Stats:**

- 21 files changed, 2,142 insertions
- ~1,365 LOC added (433 production + 932 test)
- 3 phases, 3 plans
- 1 day (2026-02-16)

**Git range:** `8911b73` → `4c40a1f`

**What's next:** Production deployment, monitoring integration, or new research features

---

## v8.0 GitHub Discovery + Gemini Analysis (Shipped: 2026-02-15)

**Delivered:** GitHub repository search and deep analysis using Gemini CLI (1M context) with dynamic prompts from paper context. Enables /research skill to find existing implementations of academic papers on GitHub.

**Phases completed:** 25-27 (3 plans total)

**Key accomplishments:**

- github_search.py module (621 LOC): GitHub REST API search, git clone, Gemini CLI/SDK analysis
- Schema v2: github_repos + github_analyses tables with 4 Pydantic models
- POST /search-github + GET /github-repos endpoints on orchestrator
- Dynamic prompt generation from paper title, abstract, and formulas
- 79 tests (44 unit + 26 integration + 9 E2E with real GitHub + Gemini APIs)
- Gemini CLI in Docker fallback to SDK with max_output_tokens

**Stats:**

- 621 LOC production + 1,307 LOC tests
- 3 phases, 3 plans
- 1 day (2026-02-15)

**Git range:** `7dccf86` → `391df79`

**What's next:** v9.0 — Pipeline Hardening (fix E2E bugs found during testing)

---

## v7.0 Orchestrator + Deploy (Shipped: 2026-02-14)

**Delivered:** End-to-end pipeline orchestration with HTTP trigger (POST /run), optional APScheduler cron (disabled by default), exponential backoff retry, and Docker Compose deployment for all 6 microservices.

**Phases completed:** 20-22 (3 plans total)

**Key accomplishments:**

- Orchestrator service (625 LOC): PipelineRunner with stage dispatch, retry (3 attempts, 1s/4s/16s backoff), pipeline status
- Docker deployment: multi-stage Dockerfile + docker-compose.yml (6 services, network_mode:host, health checks)
- 63 new tests (43 unit + 15 integration + 5 E2E), 816 LOC — total project: 495 tests
- Bug fix: DB stage→service name mapping (DB_STAGE_INDEX)
- MATLAB engine added to validator with fallback consensus (>=2 engines agree → VALID/INVALID)
- Complete pipeline: arXiv → S2/CrossRef → LLM analysis → PDF/RAG → LaTeX regex → CAS consensus → SymPy codegen

**Stats:**

- 29 files changed, 3,528 insertions
- 850 LOC service + 816 LOC tests = 1,666 LOC
- 3 phases, 3 plans
- 1 day (2026-02-14)

**Git range:** `e4a0f0e` → `7dccf86`

**What's next:** Production deployment, monitoring integration (Prometheus alerts, Grafana dashboard)

---

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

## v13.0 Production Hardening (Shipped: 2026-02-23)

**Delivered:** Server concurrency with ThreadingHTTPServer, Prometheus /metrics on all 6 services, Docker production hardening (log rotation, memory limits, init, graceful shutdown), and full monitoring integration (VictoriaMetrics scrape, Grafana dashboard, alert rules).

**Phases completed:** 43-46 (6 plans total)

**Key accomplishments:**

- ThreadingHTTPServer + 10MB body size limit + SQLite thread safety on all 6 services
- Stuck pipeline run cleanup at orchestrator startup (running → failed with reason)
- Prometheus /metrics on ports 8770-8776: request counters, duration histograms, error counts, pipeline metrics
- Docker production hardening: json-file log rotation (10MB/3 files), memory limits (512MB/1GB), init:true, stop_grace_period
- process-exporter regex for 6 PePeRS services + VictoriaMetrics scrape config with honor_labels
- Grafana dashboard (6 panels: service health, throughput, latency, errors, formulas, active runs) + provisioned alert rules

**Stats:**

- 13 files changed, 1,274 insertions, 75 deletions
- ~1,200 LOC added (production + tests)
- 4 phases, 6 plans
- 3 days (2026-02-21 to 2026-02-23)

**Git range:** `d2cb1b7` → `397a0ac`

**What's next:** TBD — monitoring extensions, performance optimization, or new features

---

