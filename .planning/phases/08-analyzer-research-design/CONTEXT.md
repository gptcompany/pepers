# Phase 8: Analyzer Research & Design — Context

**Date:** 2026-02-13
**Source:** /gsd:discuss-phase 8

## Phase Goal

Research Gemini CLI/SDK and Ollama APIs. Design 5-criteria scoring prompt, LLM fallback chain, threshold strategy, and prompt versioning approach.

## Design Decisions

### D-14: LLM Client Architecture — Funzioni Separate + fallback_chain()

**Decision:** 3 funzioni indipendenti orchestrate da `fallback_chain()`.

```
call_gemini_cli(prompt, model) → dict
call_gemini_sdk(prompt, model) → dict
call_ollama(prompt, model) → dict
fallback_chain(prompt) → dict  # tries in order, catches errors
```

**Rationale:** KISS, ogni funzione ~30 LOC, facile da testare/mockare individualmente. Nessuna classe necessaria.

**Fallback order:** Gemini CLI → Gemini SDK → Ollama
- Gemini CLI: più veloce (subprocess, OAuth quota 1000 RPD)
- Gemini SDK: backup (free tier 250 RPD per Flash)
- Ollama: sempre disponibile locale (qwen3:8b, no rate limit)

**Error handling:** Ogni funzione fa raise su errore, `fallback_chain()` cattura e prova il prossimo. Log warning su ogni fallback.

### D-15: Scoring — Media Semplice (Equal Weight)

**Decision:** 5 criteri, ciascuno scored 0.0-1.0, overall = mean(5 scores).

| Criterio | Descrizione |
|----------|-------------|
| `kelly_relevance` | Pertinenza al Kelly criterion e portfolio sizing |
| `mathematical_rigor` | Formalizzazione matematica (formule, prove, derivazioni) |
| `novelty` | Contributo originale rispetto a letteratura esistente |
| `practical_applicability` | Implementabilità pratica (dati reali, codice, backtest) |
| `data_quality` | Qualità dei dati e della metodologia sperimentale |

**JSON output format dal LLM:**
```json
{
  "scores": {
    "kelly_relevance": 0.8,
    "mathematical_rigor": 0.7,
    "novelty": 0.5,
    "practical_applicability": 0.9,
    "data_quality": 0.6
  },
  "overall": 0.7,
  "reasoning": "Brief explanation of scoring rationale"
}
```

**Note:** `overall` nel JSON è ignorato — calcolato deterministicamente come mean(5 scores) nel codice Python. Il campo esiste solo per consistency check.

### D-16: Prompt Versioning — Colonna DB

**Decision:** Aggiungere colonna `prompt_version TEXT` alla tabella `papers`.

- Prompt template in `services/analyzer/prompt.py` con costante `PROMPT_VERSION = "v1"`
- Ogni analisi scrive la versione del prompt usato nel DB
- Score comparabili solo tra papers con stessa `prompt_version`
- Schema migration: `ALTER TABLE papers ADD COLUMN prompt_version TEXT`

### D-17: Threshold — 0.7 (Restrittivo)

**Decision:** Soglia di default 0.7.

- Papers con `overall >= 0.7` → `stage='analyzed'` (passa al downstream)
- Papers con `overall < 0.7` → `stage='rejected'` (non processati ulteriormente)
- Configurabile via `RP_ANALYZER_THRESHOLD` env var
- ~60% dei papers verranno filtrati, risparmiando risorse di extraction/validation/codegen

## Architecture Alignment

### Service Pattern (da Discovery)
- `AnalyzerHandler(BaseHandler)` con `@route("POST", "/process")`
- `load_config("analyzer")` → porta 8771
- `BaseService("analyzer", 8771, AnalyzerHandler, db_path)`
- Stesse convenience: `/health`, `/status` auto-registrate

### Database Integration
- Read: `SELECT * FROM papers WHERE stage='discovered' ORDER BY created_at ASC LIMIT ?`
- Update success: `UPDATE papers SET stage='analyzed', score=?, prompt_version=? WHERE id=?`
- Update reject: `UPDATE papers SET stage='rejected', score=?, prompt_version=? WHERE id=?`
- Schema change: ADD COLUMN `prompt_version TEXT` to papers

### /process Endpoint Design

**Request:**
```json
{
  "paper_id": 42,        // Optional: analyze specific paper
  "max_papers": 10,      // Optional: batch limit (default 10)
  "force": false          // Optional: reprocess already analyzed
}
```

**Response:**
```json
{
  "papers_analyzed": 5,
  "papers_accepted": 3,
  "papers_rejected": 2,
  "avg_score": 0.68,
  "llm_provider": "gemini_cli",
  "prompt_version": "v1",
  "errors": [],
  "time_ms": 12345
}
```

## Research Summary (from RESEARCH.md)

- **Gemini CLI:** subprocess con `stdin=DEVNULL`, `GOOGLE_API_KEY` env, `-e none`, `--output-format json`
- **Gemini SDK:** `google-genai` package, `response_mime_type='application/json'`, timeout via `HttpOptions`
- **Ollama:** `POST /api/generate` con `"format": "json"`, `"stream": false`
- **Key gotcha:** Gemini CLI può hangare senza `stdin=DEVNULL` (GitHub #6715)
- **Key gotcha:** Gemini JSON response può contenere markdown fences (GitHub #11184)

## Dependencies

- Phase 5-7 (v2.0 Discovery): COMPLETE
- Shared library (v1.0): COMPLETE
- External services: Ollama :11434 (already deployed), Gemini CLI (installed)

## Out of Scope for Phase 8

- Implementazione codice (→ Phase 9)
- Test suite (→ Phase 10)
- systemd unit file (→ future phase)
- Prompt optimization/tuning (→ dopo dati reali)
