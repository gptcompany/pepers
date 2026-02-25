<p align="center">
  <img src="pepers_logo.png" alt="PePeRS Logo" width="100%">
</p>

# PePeRS

**Paper Extraction, Processing, Evaluation, Retrieval & Synthesis**

7 Python microservices that discover academic papers, extract LaTeX formulas, validate math with CAS engines, and generate production code. Includes an MCP Server for Claude Desktop/Cursor integration. No frameworks, no hallucinations — every formula is algebraically verified.

---

## What It Does

```
arXiv/OpenAlex  -->  LLM Analysis  -->  PDF Extraction  -->  CAS Validation  -->  Code Generation
  (Discovery)       (Analyzer)         (Extractor)         (Validator)          (Codegen)
     :8770             :8771              :8772               :8773               :8774
                                                                                    |
                                    Orchestrator (:8775) coordinates all stages     |
                                    Async HTTP API + cron scheduling                |
                                                                                    v
                                    MCP Server (:8776) — SSE interface         Python / C99 / Rust
                                    for Claude Desktop / Cursor
```

**Pipeline flow**: Paper discovery -> LLM relevance scoring -> PDF formula extraction -> Multi-CAS validation (SymPy + Maxima + MATLAB consensus) -> Code generation with batch LLM explanations.

## Features

| Feature | What It Does |
|---------|-------------|
| **Multi-source Discovery** | arXiv + OpenAlex (200M+ works) + Semantic Scholar + CrossRef enrichment |
| **LLM Analysis** | 5-criteria relevance scoring with configurable fallback chain (Gemini, Claude, Codex, OpenRouter, Ollama) |
| **Formula Extraction** | PDF -> RAGAnything text -> 5-pass LaTeX regex with complexity filtering |
| **CAS Validation** | Multi-engine consensus: SymPy + Maxima + MATLAB. Both must agree = VALID |
| **Code Generation** | SymPy `codegen()` for C99/Rust/Python + batch LLM explanations |
| **GitHub Discovery** | Search GitHub for paper implementations, analyze with Gemini |
| **Async Pipeline** | `POST /run` returns HTTP 202, poll `GET /runs` for progress |
| **RAG Search** | Semantic search over processed papers via RAGAnything knowledge graph |
| **MCP Server** | SSE interface with 8 tools for Claude Desktop/Cursor. Arcade flavor output! |
| **Notifications** | Apprise (90+ targets): Discord, Slack, Telegram, email, etc. |
| **Deterministic LLM** | `temperature=0`, `seed=42` on all configurable providers |

## Install

### Option 1: Setup Wizard (recommended)

```bash
git clone https://github.com/gptcompany/pepers.git
cd pepers
uv sync --extra setup
pepers-setup          # Interactive guided setup
```

The wizard checks prerequisites, configures `.env`, verifies external services, and optionally starts Docker Compose.

Subcommands: `pepers-setup check | config | services | docker | verify`

### Option 2: Docker

```bash
git clone https://github.com/gptcompany/pepers.git
cd pepers
cp .env.example .env  # Configure API keys
docker compose up -d  # Starts all 7 services + MCP server
```

**Note**: The Docker image now bundles Node.js 20 and all LLM CLI providers (`claude`, `codex`, `gemini`). No host-side installation is required for these tools.

### Option 3: uv (standalone MCP server)

```bash
uv tool install git+https://github.com/gptcompany/pepers.git
pepers-mcp --port 8776 --flavor arcade
```

### Option 4: Development

```bash
git clone https://github.com/gptcompany/pepers.git
cd pepers
uv sync --all-extras
python3 -c "from shared.db import init_db; init_db('data/research.db')"
```

## Quick Start

```bash
# Run the setup wizard first
pepers-setup

# Run all services (Docker)
docker compose up -d

# Or run individually (systemd)
sudo systemctl start rp-pipeline.target

# Start MCP server standalone
pepers-mcp  # or: python -m services.mcp

# Trigger a pipeline run
curl -X POST http://localhost:8775/run \
  -H "Content-Type: application/json" \
  -d '{"query": "abs:\"Kelly criterion\" AND cat:q-fin.*"}'
# Returns HTTP 202 with run_id

# Check progress
curl http://localhost:8775/runs?id=<run_id>

# Search papers (RAG semantic search)
curl -X POST http://localhost:8775/search \
  -H "Content-Type: application/json" \
  -d '{"query": "optimal portfolio allocation"}'
```

## Architecture

```
pepers/
├── shared/              # Common library (db, models, server, config, llm)
│   ├── db.py            # SQLite WAL + migrations (schema v4)
│   ├── models.py        # 13 Pydantic models
│   ├── server.py        # Base HTTP server + @route decorator
│   ├── config.py        # RP_ env var loader
│   ├── llm.py           # Multi-provider LLM (6 providers + fallback chain)
│   └── cli_providers.json
├── services/
│   ├── discovery/       # arXiv + S2 + CrossRef (:8770)
│   ├── analyzer/        # LLM scoring (:8771)
│   ├── extractor/       # PDF + LaTeX (:8772)
│   ├── validator/       # CAS consensus (:8773)
│   ├── codegen/         # Code gen + batch explain (:8774)
│   ├── orchestrator/    # Pipeline + API + cron (:8775)
│   └── mcp/             # MCP Server SSE (:8776)
├── tests/               # 850+ tests (unit, integration, e2e)
├── deploy/              # 7 systemd .service + .target
├── docker-compose.yml   # All services, host networking
└── Dockerfile           # Multi-stage build
```

## Configuration

All config via environment variables with `RP_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `RP_DB_PATH` | `data/research.db` | SQLite database path |
| `RP_LOG_LEVEL` | `INFO` | Logging level |
| `RP_LLM_FALLBACK_ORDER` | `gemini_cli,codex_cli,...` | LLM provider priority |
| `RP_LLM_TEMPERATURE` | `0.0` | LLM temperature (determinism) |
| `RP_NOTIFY_URLS` | — | Apprise notification URLs (CSV) |
| `RP_ORCHESTRATOR_CRON` | `0 8 * * *` | Daily pipeline schedule |
| `RP_DISCOVERY_SOURCES` | `arxiv` | Paper sources: `arxiv`, `openalex` (comma-separated) |
| `RP_ORCHESTRATOR_CRON_ENABLED` | `false` | Enable cron scheduler (disabled by default) |
| `RP_MCP_PORT` | `8776` | MCP Server SSE port |
| `RP_MCP_FLAVOR` | `arcade` | MCP output flavor: `arcade` or `plain` |

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for full configuration reference.

## API Endpoints

### Orchestrator (:8775)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST /run` | Trigger async pipeline (HTTP 202) |
| `GET /runs` | List/poll pipeline runs |
| `POST /search` | RAG semantic search |
| `GET /papers` | List papers by stage |
| `GET /formulas` | List formulas by paper |
| `GET /generated-code` | Get generated code |
| `POST /search-github` | Search GitHub for implementations |
| `GET /github-repos` | List discovered repos |

### MCP Server (:8776)

8 tools available via SSE transport for Claude Desktop, Cursor, and other MCP clients:

| Tool | Description |
|------|-------------|
| `search_papers` | RAG semantic search (fast `context_only` mode available) |
| `list_papers` | List papers by pipeline stage |
| `get_paper` | Get paper details with formulas |
| `get_formulas` | Get formulas for a paper |
| `run_pipeline` | Trigger async pipeline run |
| `get_run_status` | Poll pipeline run status |
| `search_github` | Search GitHub implementations |
| `get_generated_code` | Get generated code artifacts |

### All Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET /health` | Health check (DB status, schema version) |
| `GET /status` | Service status + uptime |
| `POST /process` | Process papers/formulas |

## Tech Stack

- **Python 3.10+** — stdlib-first (`http.server`, `sqlite3`, `logging`)
- **SQLite WAL** — shared database, schema v4, 7 tables
- **Pydantic v2** — 13 data models with validation
- **SymPy** — CAS engine + C99/Rust/Python codegen
- **MCP SDK** — FastMCP with SSE transport for tool integration
- **Apprise** — 90+ notification targets
- **Docker Compose** — host networking, health checks

No web frameworks. No ORMs. No message queues.

## Stats

- **8,500+ LOC** Python across 7 services + shared library
- **850+ tests** (unit, integration, e2e) — all passing
- **13 milestones** shipped (v1.0-v13.0)
- **6 LLM providers** with configurable fallback chain
- **3 CAS engines** for mathematical consensus
- **3 codegen languages** (Python, C99, Rust)

## External Dependencies

| Service | Port | Required | Setup |
|---------|------|----------|-------|
| RAGAnything | 8767 | For PDF extraction + semantic search | `cd rag-service && rag-setup` |
| CAS Microservice | 8769 | For formula validation (SymPy + Maxima + MATLAB) | `cd cas-service && cas-setup` |
| Ollama | 11434 | For local LLM (optional, fallback chain) | `curl -fsSL https://ollama.ai/install.sh \| sh` |

Each external service has its own setup wizard. Run `pepers-setup services` to check their availability.

## License

Internal project.

---

**Docs**: [Architecture](docs/ARCHITECTURE.md) | [Runbook](docs/RUNBOOK.md)
