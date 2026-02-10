# Phase 1: Research & Design - Context

**Gathered:** 2026-02-10
**Status:** Ready for planning

<vision>
## How This Should Work

The shared library is the foundation for all 5 microservices + orchestrator. It lives as a `shared/` directory in the monorepo — every service imports from it directly. No packaging overhead, no installation ceremony.

The architecture should be clean and well-organized, not a copy-paste of the CAS microservice. The CAS is a reference to understand what works, but the shared lib should have its own clean design.

The primary consumers of these microservices are AI agents running autonomously — they call the services via `/research` and `/research-papers` commands. This means APIs must be predictable, responses must be structured JSON, and errors must be clear enough for automated systems to handle without human intervention.

</vision>

<essential>
## What Must Be Nailed

- **Clean architecture** — Well-organized module structure that's intuitive and maintainable. Pulizia over speed.
- **AI-agent friendly APIs** — Predictable JSON responses, clear error codes, structured output that automated agents can parse and act on reliably.
- **Independence from N8N** — Zero references to N8N containers, tables, or infrastructure. SQLite file-based, fully self-contained.

</essential>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. User trusts builder judgment on structure and patterns.

Key technical choices already decided:
- SQLite (not PostgreSQL) for zero-infra overhead
- http.server stdlib (no frameworks)
- Monorepo with shared/ directory
- Single venv for all services
- PYTHONPATH-based imports via systemd units
- dotenvx for secrets, aligned with SSOT

</specifics>

<notes>
## Additional Context

The CAS microservice (:8769, 1090 LOC, in /media/sam/1TB/N8N_dev/) is the reference pattern to analyze — not to copy verbatim. It demonstrates http.server usage, systemd integration, and endpoint structure. The shared lib should extract the good patterns and improve on the weaknesses.

Future milestones will build one service at a time on top of this foundation: Discovery → Analyzer → Extractor → Validator → Codegen → Orchestrator.

</notes>

---

*Phase: 01-research-design*
*Context gathered: 2026-02-10*
