# v12.0 — Distribution & Branding

> Decisioni prese nella sessione 2026-02-19. Questo file serve come handoff per la prossima sessione.

## Completato in questa sessione

- [x] **Apprise notifiche multi-target** — `services/orchestrator/notifications.py` (68 LOC), hook in `_run_pipeline_async()` e `_cron_run()`, env var `RP_NOTIFY_URLS`, 9 unit test, `uv add apprise`
- [x] **POST /search endpoint** — semantic search via RAGAnything knowledge graph in `services/orchestrator/main.py`, fallback SQLite, helper `_query_rag()`, 5 unit test
- [x] **Documentazione** — ARCHITECTURE.md aggiornato, skill `/research-papers` aggiornata per semantic search
- [x] **uv** come package manager — `uv.lock` generato, `uv sync --all-extras` funzionante

## Prossimi passi (ordinati per priorità)

### Phase 1: MCP Server SSE

**Decisione**: MCP SSE (non stdio) perché:
- Pipeline ha SQLite → singolo writer necessario
- Già 6 servizi systemd → un 7° è naturale
- Un server, N client (Claude Desktop, Cursor, etc.)

**Architettura**:
```
Claude Desktop/Code/Cursor ──SSE──► MCP Server (:8776) ──HTTP──► Orchestrator (:8775)
                                        │
                                   1 processo, ~60MB
```

**NOTA CRITICA**: Il `POST /query` di RAGAnything chiama un LLM interno (GPT-4o-mini/Ollama) per sintetizzare → lento (30-90s). Soluzione: usare `only_need_context=True` in LightRAG per ottenere solo i chunk rilevanti (1-2s), e lasciare che il client (Claude/Desktop) faccia la sintesi. Richiede ~10 LOC di modifica al wrapper HTTP di RAGAnything per supportare un parametro `context_only`.

**Tool da esporre via MCP**:
- `search_papers(query, mode)` → POST /search (RAG semantic)
- `list_papers(stage, limit)` → GET /papers
- `get_paper(paper_id)` → GET /papers?id=X
- `get_formulas(paper_id)` → GET /formulas?paper_id=X
- `run_pipeline(query, stages)` → POST /run
- `search_github(paper_id)` → POST /search-github
- `get_generated_code(paper_id)` → GET /generated-code?paper_id=X

**Stack**: Python `mcp` SDK, SSE transport, ~250 LOC wrapper
**Dipendenza**: `uv add mcp`
**Deploy**: systemd unit `rp-mcp.service` su porta 8776

### Phase 2: Branding & Naming

**Candidati discussi** (tutti cartoon + scienza):
| Nome | Ref | Perché |
|------|-----|--------|
| **Dexter** | Dexter's Lab | Scienziato, laboratorio |
| **Beaker** | Muppets | Doppio senso (lab + personaggio) |
| **Farnsworth** | Futurama | "Good news everyone!" |
| **Neutron** | Jimmy Neutron | Genio, corto |

**Pattern open-source**: nome fun + README professionale + logo carino (Celery, Flask, Pandas)

**TODO**:
- Scegliere nome definitivo
- Generare logo (image gen o SVG)
- Rinominare repo/package
- Aggiornare pyproject.toml name

### Phase 3: Consolidamento One-Click Install

**Decisione**: Docker + uv (Python package manager, già in uso)

**Distribuzione per utente finale**:
```bash
# Opzione A: Docker (amico con ChatGPT/Claude Desktop)
docker run -p 8776:8776 nomeprogetto/mcp-server

# Opzione B: uv (sviluppatore)
uv tool install nomeprogetto
```

**TODO**:
- Dockerfile multi-stage (tutti i servizi)
- docker-compose.yml consolidato (pipeline + RAGAnything + MCP)
- `uv tool install` per CLI standalone
- OpenAPI spec auto-generata (FastAPI già lo fa) → ChatGPT Custom GPTs

### Phase 4: OpenAPI per ChatGPT

**Già gratis** perché l'orchestrator ha endpoint HTTP REST.
Serve solo generare/pulire la OpenAPI spec e creare un Custom GPT.

### Phase 5: Multi-Source Discovery (oltre arXiv)

**Attuale**: solo arXiv (+ S2/CrossRef per enrichment)
**Gap**: papers non-math (biomedicina, CS, ingegneria) non vengono trovati

**Fonti da aggiungere** (priorità):
1. **OpenAlex** — 200M+ works, gratuito, no API key, copre tutto → catch-all
2. **PubMed** (Entrez API) — biomedicina, gratuito
3. **CORE** — open access globale, API key gratuita
4. **DBLP** — computer science, gratuito

Pattern: aggiungere un `source` field in `papers` table, adapter pattern nel Discovery service per supportare N fonti configurabili via `RP_DISCOVERY_SOURCES=arxiv,openalex,pubmed`.

### Phase 6: RAGAnything context_only mode

Aggiungere parametro `context_only=true` al `POST /query` di RAGAnything per ritornare solo i chunk rilevanti senza chiamata LLM (1-2s invece di 60-90s). Il client (Claude/Cursor) sintetizza. ~10 LOC nel wrapper HTTP.

## Decisioni architetturali confermate

| Decisione | Rationale |
|-----------|-----------|
| **SQLite resta** | Volume basso (~10 papers/giorno), RAGAnything copre semantic search |
| **No FTS5/LanceDB/pgvector** | RAGAnything/LightRAG ha già knowledge graph + vector + reranking |
| **MCP SSE non stdio** | SQLite single writer, zero duplicazione processi |
| **uv non pip** | Lockfile, veloce, moderno, già configurato |
| **Apprise non custom webhook** | 90+ target, 0 logica custom, CSV env var |
| **Notifiche desktop NO** | Responsabilità del client, Discord/Apprise copre |

## File chiave modificati in questa sessione

```
services/orchestrator/notifications.py  — NUOVO (68 LOC)
services/orchestrator/main.py           — +import, +_query_rag, +POST /search, +_search_fallback, +notify hooks
tests/unit/test_notifications.py        — NUOVO (9 test)
tests/unit/test_orchestrator.py         — +5 test (QueryRag, SearchFallback)
ARCHITECTURE.md                         — Aggiornato (Apprise, RAG query, env vars)
~/.claude/commands/research-papers.md   — Aggiornato (semantic search primary)
pyproject.toml                          — +apprise>=1.9 (via uv add)
uv.lock                                 — NUOVO (generato da uv)
```

## Test status

**514/514 unit test passano** (uv run python -m pytest tests/unit/ -v)
