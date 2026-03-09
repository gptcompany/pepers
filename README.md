<p align="center">
  <img src="pepers_logo.png" alt="PePeRS Logo" width="100%">
</p>

# 🚀 PePeRS

![CI](https://github.com/gptcompany/pepers/actions/workflows/ci.yml/badge.svg?branch=main)
![Sandbox Validation](https://github.com/gptcompany/pepers/actions/workflows/sandbox-validate.yml/badge.svg?branch=main)
![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/gptprojectmanager/ac39e6516b7114f96b84ba445b8e7a83/raw/pepers-coverage.json)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/github/license/gptcompany/pepers?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/gptcompany/pepers?style=flat-square)
![Issues](https://img.shields.io/github/issues/gptcompany/pepers?style=flat-square)
![Lines of Code](https://sloc.xyz/github/gptcompany/pepers)

**Paper Extraction, Processing, Evaluation, Retrieval & Synthesis**

7 Python microservices that discover academic papers, extract LaTeX formulas, validate math with CAS engines, and generate production code. Includes an MCP Server with HTTP + SSE interfaces for Claude Desktop/Cursor integration. No frameworks, no hallucinations — every formula is algebraically verified.

> [!TIP]
> **Academic Inspiration**: This project is inspired by the research of mathematician <a href="https://www.cmup.pt/user/555" target="_blank">Samuel A. Lopes</a> PhD (University of Porto). His work in representation theory and algebraic structures informs the structural rigor that PePeRS strives to preserve when bridging the gap between theoretical mathematical expression and automated computational synthesis.

**LLM access modes supported**
- Local models (via `Ollama`)
- CLI subscriptions / local CLIs (e.g. `Claude`, `Codex`, `Gemini`)
- API keys (e.g. OpenAI, Anthropic, Google Gemini, OpenRouter)

---

## What It Does

```text
+-----------------------------+
| Sources                     |
| arXiv / OpenAlex            |
+-----------------------------+
              |
              v
+-----------------------------+
| Discovery        (:8770)    |
+-----------------------------+
              |
              v
+-----------------------------+
| LLM Analyzer     (:8771)    |
+-----------------------------+
              |
              v
+-----------------------------+
| PDF Extractor    (:8772)    |
+-----------------------------+
              |
              v
+-----------------------------+
| CAS Validator    (:8773)    |
+-----------------------------+
              |
              v
+-----------------------------+
| Code Generator   (:8774)    |
| Outputs: Python / C99 / Rust|
+-----------------------------+

+-----------------------------+
| Orchestrator API (:8775)    |
| Async HTTP API + cron       |
| Coordinates all stages      |
+-----------------------------+

+-----------------------------+
| MCP Server       (:8776)    |
| HTTP + SSE (11 tools)       |
| Claude Desktop / Cursor     |
+-----------------------------+
```

Default local ports: `:8770-:8776` (override in `.env`).

**Orchestrated mode (recommended)**: the Orchestrator (`:8775`) runs the end-to-end pipeline (discovery -> analysis -> extraction -> CAS validation -> code generation) and coordinates the other services.

**Standalone mode**: each microservice also exposes its own HTTP API and can be run/queried independently for debugging, testing, or partial integrations.

## Features

| Feature | What It Does |
|---------|-------------|
| **Multi-source Discovery** | arXiv + OpenAlex (200M+ works) + Semantic Scholar + CrossRef enrichment |
| **LLM Analysis** | 5-criteria relevance scoring with configurable fallback chain (Gemini, Claude, Codex, OpenRouter, Ollama) |
| **Formula Extraction** | PDF -> RAGAnything text -> 5-pass LaTeX regex with complexity filtering |
| **CAS Validation** | Multi-engine consensus: SymPy + SageMath (required); MATLAB + WolframAlpha (optional). All available engines must agree = VALID |
| **Code Generation** | SymPy `codegen()` for C99/Rust/Python + batch LLM explanations |
| **GitHub Discovery** | Search GitHub for paper implementations, analyze with Gemini |
| **Async Pipeline** | `POST /run` returns HTTP 202, poll `GET /runs` for progress |
| **RAG Search** | Semantic search over processed papers via RAGAnything knowledge graph |
| **Custom Notations** | Define custom LaTeX macros (e.g. `\Expect`, `\KL`) expanded before CAS validation |
| **MCP Server** | HTTP + SSE interface with 11 tools for Claude Desktop/Cursor. Arcade flavor output! |
| **Notifications** | Apprise (90+ targets): Discord, Slack, Telegram, email, etc. |
| **Deterministic LLM** | `temperature=0`, `seed=42` on all configurable providers |

## 🛠️ Install

### Option 1: Setup Wizard (recommended)

```bash
git clone https://github.com/gptcompany/pepers.git
cd pepers
./pepers-setup        # Step-by-step by default (auto-bootstrap)
# use --non-interactive for quick start
# or: ./pepers-setup --non-interactive
```

The wizard checks prerequisites, configures `.env`, verifies external services, and optionally starts Docker Compose.
It also includes an explicit MCP target selection step for `Claude Code`, `Claude Desktop`, or both.

Subcommands: `pepers-setup easy | walkthrough | guided | check | config | services | docker | verify`

When to use each mode:
- `walkthrough` (default): linear setup from top to bottom.
- `guided`: interactive menu for reconfiguration (edit existing settings, rerun specific steps, or partial updates).

Optional (global command from any folder):

```bash
cd /path/to/pepers
./pepers-setup --install-user-cmd   # installs ~/.local/bin/pepers-setup (no sudo)
pepers-setup

# system-wide alternative
sudo ln -sf "$(pwd)/pepers-setup" /usr/local/bin/pepers-setup
pepers-setup
```

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
./pepers-setup

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

### macOS note: `pepers-setup` not found

If `pepers-setup` is not found globally, run it from the repo root:

```bash
cd /path/to/pepers
./pepers-setup
```

`./pepers-setup` auto-installs `uv` (if missing), creates `.venv`, and starts the wizard.

### Clean-room Docker setup (macOS)

If you want a fully isolated, disposable setup on macOS (fresh `.env`, fresh containers, no state):

```bash
mkdir -p ~/pepers-clean && cd ~/pepers-clean
git clone https://github.com/gptcompany/pepers.git
cd pepers
cp .env.example .env

export COMPOSE_PROJECT_NAME=pepers_clean
docker compose up -d --build

# quick health checks
curl -fsS http://localhost:8775/health | python -m json.tool
curl -fsS http://localhost:8776/sse --max-time 3 || true

# teardown + remove volumes
docker compose down -v
```

## Architecture

```
pepers/
├── shared/              # Common library (db, models, server, config, llm)
│   ├── db.py            # SQLite WAL + migrations (schema v6)
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
├── tests/               # Unit, integration, e2e
├── deploy/              # 7 systemd .service + .target
├── docker-compose.yml   # All services, host networking
└── Dockerfile           # Multi-stage build
```

## 📝 Configuration

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

11 tools available via HTTP + SSE transport for Claude Desktop, Cursor, and other MCP clients:

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
| `add_notation` | Add/update custom LaTeX notation |
| `list_notations` | List all custom notations |
| `remove_notation` | Remove a custom notation |

#### Guided Workflows (MCP Prompts)

Claude Desktop users can access pre-built workflow prompts from the prompt menu:

| Prompt | What It Does |
|--------|-------------|
| `research_workflow` | Full end-to-end: discover → extract → validate → codegen → search |
| `paper_deep_dive` | Explore a single paper: formulas, code, GitHub repos |
| `setup_notations` | Define custom LaTeX macros before extraction |

**Example conversation in Claude Desktop:**

```
User: I want to research papers about the Kelly criterion in portfolio optimization.

Claude: I'll use the PePeRS research workflow. Let me start the pipeline...
  → run_pipeline(query="Kelly criterion portfolio optimization", stages=5)
  → get_run_status(run_id="run-abc123")  [polls until completed]
  → list_papers(stage="codegen")  [shows 8 papers found]
  → get_paper(paper_id=42)  [shows details of best-scored paper]
  → get_generated_code(paper_id=42)  [shows Python implementation]
```

### All Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET /health` | Health check (DB status, schema version) |
| `GET /status` | Service status + uptime |
| `POST /process` | Process papers/formulas |

## Tech Stack

- **Python 3.10+** — stdlib-first (`http.server`, `sqlite3`, `logging`)
- **SQLite WAL** — shared database, schema v6, 9 tables
- **Pydantic v2** — 13 data models with validation
- **SymPy** — CAS engine + C99/Rust/Python codegen
- **MCP SDK** — FastMCP with HTTP + SSE transport for tool integration
- **Apprise** — 90+ notification targets
- **Docker Compose** — host networking, health checks

No web frameworks. No ORMs. No message queues.

## Technical Highlights

- **6 LLM providers** with configurable fallback chain (Gemini, Claude, Codex, OpenRouter, Ollama, OpenAI)
- **4 CAS engines** for mathematical consensus: SymPy + SageMath (required), MATLAB + WolframAlpha (optional)
- **3 codegen targets** — Python, C99, Rust via SymPy `codegen()`

## External Dependencies

| Service | Port | Required | Setup |
|---------|------|----------|-------|
| RAGAnything | 8767 | For PDF extraction + semantic search | `cd rag-service && rag-setup` |
| CAS Microservice | 8769 | For formula validation (SymPy + SageMath; optional MATLAB, WolframAlpha) | `cd cas-service && cas-setup` |
| Ollama | 11434 | For local LLM (optional, fallback chain) | `curl -fsSL https://ollama.ai/install.sh \| sh` |

Each external service has its own setup wizard. Run `pepers-setup services` to check availability and boot persistence (`systemd` / Docker restart policy / `@reboot`).

## License

Internal project.

---

**Docs**: [Architecture](docs/ARCHITECTURE.md) | [Runbook](docs/RUNBOOK.md)
