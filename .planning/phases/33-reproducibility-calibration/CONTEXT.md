# Context: Phase 33 — Reproducibility & Calibration

## Phase Goal

Make pipeline deterministic and align documentation to measured reality.

## Scope Items

### 1. LLM Temperature Fix (Determinism)

**Current state** — temperature hardcoded in multiple places:

| Component | File | Line | Current Temp | Target |
|-----------|------|------|-------------|--------|
| Gemini CLI | shared/llm.py | 52-95 | NOT SET (provider default) | 0 |
| Gemini SDK | shared/llm.py | 130 | 0.3 | 0 |
| OpenRouter | shared/llm.py | 170 | 0.3 | 0 |
| Ollama (default) | shared/llm.py | 220 | 0.3 | 0 |
| Codegen explain (Ollama) | services/codegen/explain.py | 72 | 0.2 | 0 |
| Codegen explain (fallback) | services/codegen/explain.py | 80-83 | 0.3 / NOT SET | 0 |

**Approach**: Add `RP_LLM_TEMPERATURE` env var to `shared/config.py` (float, default `0.0`), use it in all LLM calls. Default to `0` for determinism.

**Order of operations** (from confidence gate feedback):
1. Add `RP_LLM_TEMPERATURE` to config.py with `float()` parsing + fallback
2. Refactor `fallback_chain()` to accept and thread `temperature` parameter
3. Update all 4 provider functions to use configurable temperature
4. Update `services/codegen/explain.py` to use config temperature

**Key constraint**: `fallback_chain()` in shared/llm.py doesn't accept/pass temperature — needs refactoring FIRST before dependent callers can be updated.

**Seed parameter**: For true reproducibility, also add `seed` parameter where providers support it (OpenRouter, Ollama). Gemini CLI doesn't support seed. This improves determinism beyond just temperature=0.

**No RP_LLM_TEMPERATURE exists** in config.py or .env currently.

### 2. ARCHITECTURE.md Full Refresh

**Discrepancies found** (9 issues):

| Issue | Severity | Current Value | Actual Value |
|-------|----------|--------------|--------------|
| Test count | CRITICAL | 103 | 668 |
| Service status | CRITICAL | "Not implemented" | All 6 fully built |
| Schema version | HIGH | v1 | v3 |
| Unit test split | HIGH | 77 unit + 10 integration | 445 unit + 169 integration + 54 E2E |
| Shared library LOC | MEDIUM | 816 | 1,313 |
| Missing llm.py module | MEDIUM | Not documented | 291 LOC |
| Last validated date | MEDIUM | 2026-02-10 | 2026-02-17 |
| Timeout config | LOW | Not mentioned | RP_ORCHESTRATOR_TIMEOUT=300, LLM timeouts |
| Directory tree | MEDIUM | Incomplete | Missing services/*, deploy/*, docs/ |

### 3. Verification — Determinism Test

**Plan**: Run analyzer 3x on same paper → assert identical relevance scores.

**Category**: Slow/manual calibration test — NOT for CI/CD. Mark as `@pytest.mark.slow` or `@pytest.mark.calibration`. Run manually or in scheduled nightly jobs only.

**Requires**: Services running (or test with mock server), same LLM backend, temperature=0.

## Constraints

- Temperature changes must be backwards-compatible (env var with default)
- ARCHITECTURE.md must reflect ALL current services, endpoints, schema, test counts
- Determinism test needs real LLM call (not mock) — marks as E2E
- Schema version in ARCHITECTURE.md must say v3

## Files to Modify

1. `shared/config.py` — add RP_LLM_TEMPERATURE
2. `shared/llm.py` — use RP_LLM_TEMPERATURE in all 4 provider functions + fallback_chain
3. `services/codegen/explain.py` — use config temperature
4. `ARCHITECTURE.md` — full rewrite of stale sections
5. `tests/` — determinism test (analyzer 3x same input)

## Dependencies

- Phase 32 complete (healthcheck endpoints exist) ✅
- LLM services accessible for determinism verification
