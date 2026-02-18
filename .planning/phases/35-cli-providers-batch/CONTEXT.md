# Context: Phase 35 — CLI Providers + Batch Explain

## Phase Goal

Add claude_cli and codex_cli as data-driven LLM providers via JSON config, make fallback order configurable via env var, implement batch explain for codegen to reduce LLM calls by ~10x.

## Scope Items

### 1. CLI Provider Registry (Data-Driven)

**File created**: `shared/cli_providers.json`
- claude_cli: `claude --print --output-format json`, stdin input, `--append-system-prompt`, `--model`
- codex_cli: `npx @openai/codex exec`, arg input, no system/model flags
- gemini_cli: `gemini -p`, arg input, `-m` model flag, extra_args for json output

**File modified**: `shared/llm.py`
- `_load_cli_configs()`: loads JSON once (module-level cache)
- `call_cli(provider_name, prompt, system, model, timeout)`: generic function
- `call_claude_cli()`, `call_codex_cli()`: thin wrappers
- `call_gemini_cli()`: refactored to delegate to `call_cli()`
- `fallback_chain()`: includes claude_cli/codex_cli in provider_funcs
- `DEFAULT_FALLBACK_ORDER`: configurable via `RP_LLM_FALLBACK_ORDER` env var

### 2. Batch Explain

**File to modify**: `services/codegen/explain.py`
- `explain_formulas_batch(formulas, batch_size=10)`: chunks formulas, sends batch prompt, parses JSON array response
- Fallback: if batch parse fails, per-formula `explain_formula()`

**File to modify**: `services/codegen/main.py`
- In `handle_process()`: call `explain_formulas_batch()` first, then use cached results in per-formula loop

### 3. Tests

- `tests/unit/test_llm.py`: ~14 new tests for CLI registry, call_cli, fallback order
- `tests/unit/test_codegen.py`: ~8 new tests for batch explain

## Dependencies

- v10.0 complete (Phase 34 shipped) ✅
- `shared/llm.py` existing provider functions ✅

## Status

- Tasks 1-2 committed: 0031cbd (cli_providers.json + shared/llm.py updates)
- Tasks 3-4 pending: batch explain + tests
