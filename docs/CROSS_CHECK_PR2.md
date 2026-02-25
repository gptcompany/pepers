# Cross-Check Report — PR #2

**PR**: [fix: bundle Node.js in Docker, align setup wizard, harden services](https://github.com/gptcompany/pepers/pull/2)
**Commit**: `de3490f`
**Merged**: 2026-02-24T23:58:48Z
**Files changed**: 16 (+255/-42)
**Agents**: Claude Opus 4.6 (Docker + docker-compose + review), Codex (setup wizard + hardening)

---

## 1. Obiettivi del piano vs risultati

| Obiettivo | Stato | Evidenza |
|-----------|-------|----------|
| Rimuovere mount host Node.js da analyzer/codegen | DONE | `grep -c "host-npm\|NODE_PATH\|NPM_GLOBAL\|NODE_BIN" docker-compose.yml` = 0 |
| Installare Node.js nel container via multi-stage copy | DONE | `Dockerfile:25-26` COPY from `node:20-slim`, `Dockerfile:29` npm install 3 CLI |
| Rimuovere `RP_VALIDATOR_ENGINES` hardcoded da docker-compose | DONE | `grep -c "RP_VALIDATOR_ENGINES" docker-compose.yml` = 0 |
| Allineare nomi env nel setup wizard | DONE | `_config.py:36,39,41`, `_services.py:13,24,35`, `_verify.py:18,20,24` |
| Fix MCP health check su `/sse` | DONE | `_verify.py:14` `"mcp": "/sse"` |
| Aggiungere `--help` al wizard | DONE | `main.py:53` `if command in {"-h", "--help", "help"}` |
| Test di regressione wizard | DONE | 34/34 test passano (`test_setup_wizard.py`) |

---

## 2. Modifiche file per file

### 2.1 `Dockerfile` (+8 righe)

**Cosa**: Multi-stage copy di Node.js 20 da immagine ufficiale + npm install globale di 3 CLI.

```
Riga 25: COPY --from=node:20-slim /usr/local/bin/node /usr/local/bin/node
Riga 26: COPY --from=node:20-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
Riga 27-28: ln -s npm, npx
Riga 29: npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli
Riga 30: npm cache clean --force
```

**Verifica runtime**:
- `docker compose run --rm analyzer node --version` = `v20.20.0`
- `docker compose run --rm analyzer which claude` = `/usr/local/bin/claude`
- `docker compose run --rm codegen which gemini` = `/usr/local/bin/gemini`
- `docker compose run --rm codegen which codex` = `/usr/local/bin/codex`

**Potenziale issue**: I pacchetti npm vengono installati a build time. Se cambiano versione serve rebuild. Accettabile per CLI tools che cambiano raramente in produzione.

**Impatto dimensione immagine**: Node.js 20 slim + 3 CLI aggiungono ~300-400MB all'immagine. Trade-off accettabile vs dipendenza host.

### 2.2 `docker-compose.yml` (-9 righe)

**Righe rimosse da analyzer** (ex 63-64, 68-69):
- `PATH=/usr/local/bin:/usr/bin:/bin:/host-npm/bin`
- `NODE_PATH=/host-npm/lib/node_modules`
- `${NPM_GLOBAL:-/usr/lib/node_modules}:/host-npm:ro`
- `${NODE_BIN:-/usr/bin/node}:/usr/bin/node:ro`

**Righe rimosse da codegen** (ex 175-176, 180-181): identiche.

**Riga rimossa da validator** (ex 138):
- `RP_VALIDATOR_ENGINES=matlab,sympy,maxima`

**Conservato**: `HOME=/tmp` in analyzer (riga 62) e codegen (riga 169) — necessario per CLI tools che scrivono in `$HOME`.

**Nota**: `RP_VALIDATOR_ENGINES` rimane in `.env.example:40` come default user-configurabile e in `_config.py:38` come variabile wizard. Corretto: l'override non va hardcoded in compose, ma l'utente puo' settarlo in `.env` se vuole bypassare auto-discovery.

### 2.3 Setup Wizard (Codex)

#### `services/setup/main.py` (+5 righe)
- `_print_usage()` (riga 28-32): output usage con `markup=False` (evita troncamento rich)
- `command in {"-h", "--help", "help"}` (riga 53): 3 varianti supportate

#### `services/setup/_config.py` (+49 righe)
- `_CONFIG_VARS` espanso da ~10 a 24 variabili (righe 12-44)
- Nuove: `RP_DISCOVERY_SOURCES`, `RP_ORCHESTRATOR_CRON*`, `RP_VALIDATOR_ENGINES`, `RP_RAG_QUERY_URL`, `RP_MCP_FLAVOR`
- `_read_env_values()` (righe 47-62): legge `.env` esistente prima dei prompt
- `check()` (righe 88-99): verifica anche `RP_VALIDATOR_CAS_URL`, `RP_EXTRACTOR_RAG_URL`, `RP_CODEGEN_OLLAMA_URL`
- `install()` usa `existing_values.get(env_name)` (riga 112) come default per non sovrascrivere

#### `services/setup/_services.py` (+8 righe)
- `env_urls` ora lista con fallback legacy: `["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"]` (riga 13)
- Stessa cosa per RAG (riga 24) e Ollama (riga 35)
- `_url()` itera la lista `env_urls` (righe 55-60)

#### `services/setup/_verify.py` (+13 righe)
- `_INTERNAL_HEALTH_PATHS = {"mcp": "/sse"}` (riga 13-15): MCP non ha `/health`
- `_EXTERNAL` usa tuple di env keys con fallback (righe 17-25)
- `_env_first()` helper (righe 28-33): ritorna primo env non vuoto

#### `tests/unit/test_setup_wizard.py` (+114 righe)
- 4 nuovi test (righe 148, 196, 306, 378)
- Coprono: env names nuovi, precedenza vs legacy, MCP su `/sse`, `--help`

### 2.4 Defensive Hardening (Codex — non richiesto)

| File | Riga | Modifica | Necessita' |
|------|------|----------|-----------|
| `codegen/generators.py:300-305` | Guard `isinstance(expr, sympy.Expr)` | Alta — previene crash su `Piecewise`, `BooleanTrue`, ecc. |
| `extractor/main.py:127-128` | Guard `paper.arxiv_id is None` | Media — fail-fast con messaggio chiaro |
| `extractor/pdf.py:74` | Fallback `paper.arxiv_id or f"paper-{paper.id}"` | Media — evita `NoneType.replace()` |
| `mcp/__main__.py:8-12` | Validazione transport + `cast()` | Bassa — type safety, il default era gia' `sse` |
| `mcp/server.py:223-225, 380-382` | Guard `isinstance(result, dict)` x2 | Bassa — contratto gia' garantito dal caller |
| `orchestrator/main.py:71-73` | `_db_path_required()` helper | Bassa — pattern assert per `Optional[str]` |
| `orchestrator/github_search.py:21` | Import `urllib.error` | Alta — import mancante, poteva causare `NameError` |
| `scripts/smoke_test.py:233,463` | Guard `_existing_id is not None` | Alta — bug reale: `_reset_paper(None)` crash |

### 2.5 `.env.example` (+1 riga)

Aggiunto `RP_RAG_QUERY_URL=http://localhost:8767` (riga 47) per allineamento con orchestrator che usa questa variabile.

---

## 3. Test evidence

```
$ python -m pytest tests/ -v
880 passed, 80 deselected in 134.18s

$ python -m pytest tests/unit/test_setup_wizard.py -v
34 passed in 3.38s
```

Pre-modifica: 872 test. Post-modifica: 880 test (+8 nuovi nel wizard).

---

## 4. Checklist di validazione

| # | Check | Risultato |
|---|-------|-----------|
| 1 | `docker compose build` senza errori | PASS (7 immagini) |
| 2 | `node --version` nel container | PASS (`v20.20.0`) |
| 3 | CLI `claude`, `codex`, `gemini` disponibili | PASS (tutti in `/usr/local/bin/`) |
| 4 | Nessun volume mount host Node.js in compose | PASS (0 occorrenze) |
| 5 | Nessun `RP_VALIDATOR_ENGINES` hardcoded in compose | PASS (0 occorrenze) |
| 6 | `RP_VALIDATOR_ENGINES` resta in `.env.example` e wizard | PASS (user-configurabile) |
| 7 | Env names wizard allineati ai servizi reali | PASS (3 URL verificati) |
| 8 | MCP health check su `/sse` | PASS (`_verify.py:14`) |
| 9 | `--help` funziona | PASS (`main.py:53`) |
| 10 | Test suite completa | PASS (880/880) |
| 11 | No regressioni | PASS (0 falliti) |
| 12 | PR mergiata | PASS (`de3490f`) |

---

## 5. Rischi residui e raccomandazioni

### Rischi bassi

1. **Immagine Docker piu' grande**: +300-400MB per Node.js + CLI. Monitorare se diventa problema in CI/CD.
2. **Versioni CLI pinned a build time**: `npm install -g` installa latest. Per reproducibilita' considerare pinning esplicito (es. `@anthropic-ai/claude-code@2.1.52`).
3. **`_read_env_values()` parser semplificato**: Non gestisce valori quotati (`KEY="value with spaces"`). Sufficiente per `.env` PePeRS dove i valori non hanno spazi.

### Nessun rischio

- **RP_VALIDATOR_ENGINES**: auto-discovery attivo in `validator/main.py:406-421`, fallback a env var se CAS non raggiungibile.
- **Legacy env fallback**: `_services.py` e `_verify.py` cercano prima il nome nuovo, poi il legacy. Zero breaking change.
- **Defensive guards**: tutte le guard aggiungono early return/raise, nessuna modifica al happy path.

---

## 6. Diff summary

```
 .env.example                           |   1 +
 Dockerfile                             |   8 +++
 docker-compose.yml                     |   9 ---
 scripts/smoke_test.py                  |   4 +-
 services/codegen/generators.py         |   7 ++
 services/extractor/main.py             |   2 +
 services/extractor/pdf.py              |   2 +-
 services/mcp/__main__.py               |   6 +-
 services/mcp/server.py                 |   6 ++
 services/orchestrator/github_search.py |   1 +
 services/orchestrator/main.py          |  18 +++--
 services/setup/_config.py              |  55 +++++++++++++--
 services/setup/_services.py            |  19 ++++--
 services/setup/_verify.py              |  29 ++++++--
 services/setup/main.py                 |  12 +++-
 tests/unit/test_setup_wizard.py        | 118 +++++++++++++++++++++++++++++++--
 16 files changed, 255 insertions(+), 42 deletions(-)
```
