# Context: Phase 34 — Orchestrator Smoke Test & Documentation

## Phase Goal

Extend the existing smoke test to exercise the orchestrator's `/run` endpoint (instead of calling services directly), and create a comprehensive operational runbook for production deployment.

## Scope Items

### 1. `--via-orchestrator` Flag for smoke_test.py

**Current state** — `scripts/smoke_test.py` (452 LOC) calls each service's `/process` endpoint directly in sequence: discovery(8770) → analyzer(8771) → extractor(8772) → validator(8773) → codegen(8774).

**Target** — Add `--via-orchestrator` CLI flag that instead sends a single `POST /run` to the orchestrator (port 8775), letting it handle sequencing, retry, and batch iteration internally.

**Orchestrator `/run` contract:**
```json
POST http://localhost:8775/run
{
  "query": "id:2003.02743",
  "stages": 5,
  "max_papers": 1,
  "max_formulas": 50
}
```

**Response:**
```json
{
  "run_id": "run-...",
  "status": "completed|partial|failed",
  "stages_completed": 5,
  "results": { "discovery": {...}, "analyzer": {...}, ... },
  "errors": [],
  "time_ms": 15000
}
```

**Implementation approach:**
1. Add `--via-orchestrator` flag to argparse
2. Add orchestrator port (8775) to `SERVICE_PORTS` if flag is set
3. New function `run_smoke_test_via_orchestrator()` that:
   - Health checks orchestrator (8775) + all 5 downstream services via `GET /status/services`
   - POSTs to `/run` with `query=id:{arxiv_id}`, `stages=5`, `max_formulas=max_formulas`
   - Maps orchestrator response to `SmokeReport` format
   - Falls back to same DB verification for formula counts
4. Reuse `print_report()` and `SmokeReport` dataclass unchanged
5. PASS/FAIL criteria: same as direct mode — final stage must be "codegen"

**Key difference vs direct mode:**
- Direct: 5 separate HTTP calls + batch loops
- Orchestrator: 1 HTTP call (with long timeout), orchestrator handles retry/batch internally
- Timeout: use `RP_ORCHESTRATOR_TIMEOUT` (default 300s) — the orchestrator manages per-stage timeouts internally

**Timeout strategy (from gate feedback):**
- The smoke test does NOT need 11,000s timeout — the orchestrator handles timeouts per-stage internally
- Smoke test timeout = orchestrator timeout (300s default) + buffer = ~600s
- For faster smoke testing, use `--max-formulas 5` to limit batch size
- Progress: the orchestrator returns a single response, but the test can poll `/status` endpoint for interim progress if needed

### 2. pytest Wrapper: test_smoke_orchestrator.py

**File:** `tests/e2e/test_smoke_orchestrator.py`

**Tests to implement:**
1. `test_orchestrator_health` — orchestrator /health returns ok + downstream check via /status/services
2. `test_full_run_via_orchestrator` — POST /run with real paper, verify stages_completed=5 + DB verification
3. `test_run_single_stage` — POST /run with stages=1, verify only discovery runs
4. `test_run_with_paper_id` — POST /run with paper_id (pre-seeded in fixture), verify resume from current stage

**Markers:** `@pytest.mark.e2e`

**Test setup (from gate feedback):**
- Tests that use orchestrator with real downstream services require all 6 services running — mark with `@pytest.mark.e2e`
- `test_run_with_paper_id` must pre-seed a paper in the DB fixture at stage "discovered" before POSTing
- For tests that don't need real downstream services (health, status), use the existing `e2e_orchestrator` fixture pattern from `test_orchestrator_e2e.py`
- External API dependency mitigation: use `DEFAULT_ARXIV_ID = "2003.02743"` which is already cached in most environments; if not cached, the test naturally exercises the full pipeline

### 3. Operational Runbook (docs/RUNBOOK.md)

**Level of detail:** Comprehensive (3-5 pages)

**Sections:**
1. **Service Overview** — 6 services, ports, dependencies
2. **Startup Order** — Required sequence: DB init → discovery → analyzer → extractor → validator → codegen → orchestrator
3. **Health Check URLs** — All 6 endpoints with expected responses
4. **Systemd Management** — start/stop/restart commands, journalctl patterns
5. **Common Failure Modes**
   - Service crash during batch processing
   - DB locked (SQLite WAL contention)
   - External API rate limits (arXiv, S2, CrossRef)
   - CAS engine timeout (SymPy/Maxima/MATLAB)
   - LLM provider unreachable (Ollama/OpenRouter/Gemini)
   - Extractor PDF parsing failure (MinerU/RAGAnything)
6. **Recovery Procedures**
   - Paper stuck in intermediate stage
   - Duplicate formula detection
   - Batch iteration safety cap hit
   - Full pipeline re-run
7. **Configuration Reference** — All RP_* env vars with defaults
8. **Monitoring** — Log locations, key metrics, alert thresholds

### 4. Extractor Performance Documentation

**Include in runbook or separate section:**
- CPU vs GPU expected times for MinerU/RAGAnything
- `RP_EXTRACTOR_TIMEOUT` recommended values (CPU: 3600s, GPU: 600s)
- Pre-caching: RAGAnything first-run downloads models (~2GB)
- Memory requirements: 4GB+ for PDF processing

## Out of Scope

- Discord webhook notifications (explicitly skipped)
- New endpoints on orchestrator
- Schema changes
- Changes to downstream services

## Files to Create/Modify

1. `scripts/smoke_test.py` — add `--via-orchestrator` flag + orchestrator mode
2. `tests/e2e/test_smoke_orchestrator.py` — new E2E test file
3. `docs/RUNBOOK.md` — new operational documentation

## Dependencies

- Phase 33 complete (LLM determinism, ARCHITECTURE.md refresh) ✅
- All 6 services have /health endpoint (Phase 32) ✅
- Orchestrator /run and /status/services endpoints exist ✅

## Constraints

- smoke_test.py must remain stdlib-only (no project deps)
- Orchestrator timeout for full pipeline: ≥10,000s
- E2E tests must be marked @pytest.mark.e2e
- Runbook must reflect current production state (schema v3, 671+ tests)
