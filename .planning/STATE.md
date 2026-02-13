# State: Research Pipeline

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v3.0 Analyzer Service — COMPLETE

## Current Position

Phase: 10 of 10 (Analyzer Testing) — COMPLETE
Plan: 10-01 complete
Status: v3.0 milestone shipped
Last activity: 2026-02-13 — Phase 10 test suite (77 new tests, 91% coverage)

Progress: ██████████ 100%

## Accumulated Context

### Key Decisions
- See PROJECT.md Key Decisions table (13 decisions from v1.0)
- D-14: LLM Client — separate functions + fallback_chain() (KISS)
- D-15: Scoring — simple mean of 5 criteria (0.0-1.0 each)
- D-16: Prompt versioning — prompt_version column in papers table
- D-17: Threshold — 0.7 (restrittivo, ~60% papers filtered)

### Blockers/Concerns Carried Forward
- server.py run() method: 6 lines uncovered (process-level SIGTERM testing)
- CAS microservice: only Maxima engine works (SageMath/MATLAB broken)
- Gemini API: intermittent 503 errors, CLI hangs without stdin=DEVNULL

### Roadmap Evolution
- v1.0 Foundation: SHIPPED 2026-02-10 (4 phases, 4 plans, 103 tests)
- v2.0 Discovery Service: SHIPPED 2026-02-12 (3 phases: 5-7)
- v3.0 Analyzer Service: SHIPPED 2026-02-13 (3 phases: 8-10)

### Test Suite Summary
| Tier | Count | Scope |
|------|-------|-------|
| Unit | 60 | prompt, llm, handler, scoring, migration |
| Integration | 14 | real DB + HTTP server, mock LLM |
| E2E | 3 | real Ollama (qwen3:8b) |
| **Total new** | **77** | |
| **Project total** | **236+8** | 236 non-e2e + 8 e2e |
| Coverage | 91% | services/analyzer/ |

## Session Continuity

Last session: 2026-02-13
Stopped at: v3.0 milestone complete
Resume file: N/A — milestone shipped
Next step: Create v4.0 milestone (Extractor Service) or /gsd:complete-milestone
