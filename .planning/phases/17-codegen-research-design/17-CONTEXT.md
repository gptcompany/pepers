# Context: Phase 17 — Codegen Research & Design

## Vision

Servizio Codegen che prende formule validate (stage='validated') e produce:
1. Spiegazione plain-language via LLM (Ollama qwen3:8b)
2. Codice C99 via SymPy `codegen("C99")` (primario)
3. Codice Rust via SymPy `rust_code()` / `RustCodeGen` (secondario)
4. Codice Python via SymPy `pycode()` (sempre presente)

## Scope

### In Scope
- `services/codegen/` con 3 moduli (main, explain, generators)
- LLM explanation con Ollama-first fallback chain + JSON schema enforcement
- Multi-language codegen: C99 (primary), Rust (secondary), Python (always)
- Refactor LLM client functions da analyzer/llm.py a shared/llm.py (DRY)
- Storage in `generated_code` table (already exists in schema)
- Endpoints: /process, /health, /status
- Port: 8775

### Out of Scope
- Compilazione del codice generato (genera solo source code strings)
- Matrix codegen (Kelly criterion = formule scalari)
- autowrap / lambdify (non servono per storage)
- MATLAB codegen (validazione only, license pending)

## Key Constraints
- SymPy 1.14.0 already in venv
- `parse_latex()` richiede `antlr4-python3-runtime==4.11`
- Rust printer: bug type-casting fixato Aug 2024, issue #26967 ancora aperto (integer promotion workaround: `Symbol('k', integer=True)`)
- Ollama `num_ctx` default 2048 troppo piccolo → impostare 4096
- Kelly criterion formulas sono algebriche → nessun problema con limitazioni SymPy

## Dependencies
- v5.0 Validator complete (fornisce formule con stage='validated')
- CAS microservice running (:8769) per formule validate
- Ollama running (:11434) per LLM explanation
- Gemini API (fallback, intermittent 503/429)

## Risks
- `parse_latex()` potrebbe fallire su LaTeX non standard dal regex extractor
- Rust integer promotion issue (#26967) potrebbe generare codice invalido
- Gemini rate limiting può rallentare il fallback

## Decisions Already Made
- C99 primario (utente: "c/c++ e piu avanzato" + ricerca conferma maturità SymPy)
- Rust secondario (funzionante ma meno maturo)
- Python sempre presente (costo zero)
- Ollama-first per explanation (locale, gratis, sufficiente per 90%+ formule)
- `/no_think` per qwen3 (explanation ≠ reasoning)
