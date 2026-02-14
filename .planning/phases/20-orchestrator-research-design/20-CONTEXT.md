# Phase 20: Orchestrator Research & Design - Context

**Gathered:** 2026-02-14
**Status:** Ready for planning

<vision>
## How This Should Work

The orchestrator is the brain of the pipeline. It coordinates all 5 services (Discovery→Analyzer→Extractor→Validator→Codegen) with two modes of operation:

**Manual mode (per-paper control):** I call HTTP endpoints to advance individual papers through stages one at a time. I can see intermediate results at each stage — how a paper scored in analysis, what formulas were extracted, which passed CAS validation. This is for testing, debugging, and when I want to inspect specific papers closely.

**Automatic mode (cron):** A configurable cron scheduler runs periodically and advances ALL pending papers. The key is that the number of stages per cron run is configurable — I might want it to advance just one stage per run (conservative), or push everything through the full pipeline in one go (aggressive), or anything in between.

When a paper fails at any stage, the orchestrator retries automatically with backoff before marking it as failed. Failed papers don't block the rest of the batch.

Everything runs in Docker: one `docker-compose up` starts all 6 services with a shared SQLite volume. Health checks ensure services start in the right order.

A `/status` endpoint shows the current state of the pipeline at a glance — how many papers at each stage, when the last run happened, recent errors.

</vision>

<essential>
## What Must Be Nailed

- **Per-paper step control**: HTTP endpoints to advance individual papers through stages, seeing intermediate results at each step
- **Configurable cron**: parameter to control how many stages per cron run (1, all, or N)
- **Automatic retry with backoff**: failed papers get retried before being marked as failed, without blocking others
- **Single docker-compose**: all 6 services + SQLite volume in one compose file, health checks for startup order
- **GET /status**: quick overview of pipeline state (papers per stage, last run, errors)

</essential>

<specifics>
## Specific Ideas

- Orchestrator on port 8775 (following existing convention: 8770-8774 for services)
- Cron default: daily at 8AM, configurable via environment variable
- Stages per run: configurable parameter (default: all stages in one run)
- Status endpoint should show counts per stage (discovered: 42, analyzed: 38, etc.)
- All services in one docker-compose.yml in the research-pipeline repo root
- Docker image: python:3.12-slim with multi-stage build

</specifics>

<notes>
## Additional Context

- Phase 20 is research & design only — deliverable is DESIGN.md with API contract, Docker architecture, orchestration schema. No implementation code.
- PROJECT.md previously had "Docker containerization" as out of scope (systemd was the plan). This changes with v7.0 — PROJECT.md needs updating.
- External services (RAGAnything on 8767, CAS on 8769, Ollama on 11434) are already running on the Workstation as standalone services. Docker compose needs to connect to them, not containerize them.
- Gemini API has intermittent 503/429 errors — orchestrator retry logic should handle this gracefully.

</notes>

---

*Phase: 20-orchestrator-research-design*
*Context gathered: 2026-02-14*
