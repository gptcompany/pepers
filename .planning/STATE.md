# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-14)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** Phase 23 smoke test done — 4 critical bugs to fix

## Current Position

Phase: 23 (E2E Smoke Test with Real Papers)
Plan: 23-01 completed (1/1)
Status: **Done with issues** — 4 critical bugs block production
Last activity: 2026-02-14 — smoke test executed, SUMMARY.md written

Progress: 7/7 milestones shipped, phase 23 smoke test reveals 8 bugs

## Shipped Milestones

- v1.0 Foundation: 4 phases, 103 tests, 2091 LOC — 2026-02-10
- v2.0 Discovery: 3 phases, 448 LOC — 2026-02-12
- v3.0 Analyzer: 3 phases, 600 LOC + 1301 LOC tests — 2026-02-13
- v4.0 Extractor: 3 phases, 644 LOC + 999 LOC tests — 2026-02-13
- v5.0 Validator: 3 phases, 1178 LOC + 751 LOC tests — 2026-02-14
- v6.0 Codegen: 3 phases, 806 LOC + 960 LOC tests — 2026-02-14
- v7.0 Orchestrator + Deploy: 3 phases, 850 LOC + 816 LOC tests — 2026-02-14

## Final Stats

- **Total tests**: 497 (463 non-e2e + 34 e2e), all passing
- **Total LOC**: ~7,500+ across 6 services + shared library + Docker
- **Services**: 6 microservices (ports 8770-8775) + Docker Compose
- **Duration**: 5 days (2026-02-10 to 2026-02-14)
- **CAS engines**: MATLAB + SymPy + Maxima with fallback consensus

## Phase 23 Smoke Test Results

### Services Status
- Discovery: OK (16s/3 papers)
- Analyzer: OK (234s/3 papers, Ollama)
- Extractor: PARTIAL (path fix applied, MinerU 9.7 min/page CPU)
- Validator: OK (14s/47 formulas, SymPy+Maxima)
- Codegen: **FAIL** (antlr4 missing, GEMINI_API_KEY missing, Ollama timeout)
- Orchestrator: NOT TESTED (blocked by codegen)

### Critical Bugs (MUST FIX before production)
1. antlr4-python3-runtime missing in Docker image (codegen 100% fail)
2. GEMINI_API_KEY not passed to codegen container
3. MATLAB engine not configured in docker-compose.yml
4. Extractor timeout too short for MinerU on CPU

### Fixes Applied During Smoke Test
- docker-compose.yml: named volume → bind mount (permissions fix)
- docker-compose.yml: added RP_EXTRACTOR_PDF_HOST_DIR + RAG data mount
- rag_client.py: path mapping container→host for RAGAnything

### Hardware Benchmarks (Workstation, CPU-only)
- MinerU: 9.7 min/page (~6.2 pages/hour), 4.1GB RAM/paper
- Ollama (qwen3:8b): 78s/paper for analysis
- Validator: 14s/47 formulas
- Discovery: 16s/3 papers
- Daily batch 10 papers estimate: ~24h (UNACCEPTABLE without GPU)

## Blockers/Concerns

- MinerU on CPU is #1 bottleneck — GPU required for production
- Codegen 100% broken until antlr4 + GEMINI_API_KEY fixed
- MATLAB engine available but not configured in Docker
- CPU contention: MinerU + Ollama cannot run in parallel

## Future Tasks

- Fix 4 critical bugs from smoke test
- Re-run phase 23 after fixes to verify
- GPU setup for MinerU (or alternative parser)
- Monitoring integration: Prometheus alerts, Grafana dashboard
- RAGAnything timing feedback: ETA based on pages + hardware
- Deploy Docker stack to production

## Session Continuity

Last session: 2026-02-14
Stopped at: Phase 23 smoke test complete, 4 critical bugs identified
Resume file: See .planning/phases/23-e2e-smoke-test/23-01-SUMMARY.md
