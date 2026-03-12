"""Orchestrator service — pipeline coordination and cron scheduling.

Sixth microservice in the research pipeline. Coordinates the 5
downstream services (Discovery → Analyzer → Extractor → Validator →
Codegen) via HTTP calls to their /process endpoints.

Usage:
    python -m services.orchestrator.main

Environment:
    RP_ORCHESTRATOR_PORT=8775               # Service port (default: 8775)
    RP_ORCHESTRATOR_CRON=0 8 * * *          # Cron expression
    RP_ORCHESTRATOR_CRON_ENABLED=false      # Enable cron (default: disabled)
    RP_ORCHESTRATOR_STAGES_PER_RUN=5        # Stages per cron run
    RP_ORCHESTRATOR_DEFAULT_QUERY=...       # Default arXiv query for cron
    RP_ORCHESTRATOR_CRON_MAX_PAPERS=10      # Max papers per cron batch
    RP_ORCHESTRATOR_CRON_MAX_FORMULAS=100   # Max formulas per cron batch override
    RP_ORCHESTRATOR_RETRY_MAX=3             # Max retries per service call
    RP_ORCHESTRATOR_RETRY_BACKOFF=4.0       # Backoff base (seconds)
    RP_ORCHESTRATOR_TIMEOUT=300             # Request timeout (seconds)
    RP_DB_PATH=data/research.db             # SQLite database path
    RP_LOG_LEVEL=INFO                       # Log level
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from urllib.parse import parse_qs

from shared.config import get_default_max_formulas, load_config, resolve_localhost_url
from shared.db import init_db, transaction
from shared.models import Formula, GitHubAnalysis, GitHubRepo, Paper
from shared.rag import normalize_rag_force_parser
from shared.server import BaseHandler, BaseService, route

from services.orchestrator.github_search import search_and_analyze
from services.orchestrator.notifications import notify, notify_pipeline_result
from services.orchestrator.pipeline import PipelineRunner, RequeueError
from services.orchestrator.scheduler import create_scheduler

logger = logging.getLogger(__name__)

_RAG_URL = resolve_localhost_url(
    os.environ.get("RP_RAG_QUERY_URL", "http://localhost:8767")
)
_RAG_QUERY_TIMEOUT = int(os.environ.get("RP_RAG_QUERY_TIMEOUT", "30"))


def _resume_stuck_runs(runner: PipelineRunner) -> tuple[int, int]:
    """Resume orphaned async runs from pipeline_runs.

    Returns:
        Tuple of (resumed_count, failed_count).
    """
    resumed = 0
    failed_run_ids: list[str] = []

    for stuck in runner.get_stuck_runs():
        run_id = stuck["run_id"]
        params = stuck.get("params")
        if not isinstance(params, dict):
            failed_run_ids.append(run_id)
            continue

        _start_pipeline_thread(
            runner,
            run_id,
            query=params.get("query"),
            topic=params.get("topic"),
            paper_id=params.get("paper_id"),
            stages=int(stuck.get("stages_requested") or 5),
            max_papers=params.get("max_papers", 10),
            max_formulas=params.get("max_formulas", get_default_max_formulas()),
            force_parser=params.get("force_parser"),
            force=params.get("force", False),
        )
        resumed += 1
        logger.warning("Resuming orphaned pipeline run: %s", run_id)

    failed = runner.fail_runs(
        failed_run_ids,
        "Marked as failed: orphaned at service restart but not resumable",
    )
    return resumed, failed


def _query_rag(query: str, mode: str = "hybrid", context_only: bool = False) -> dict:
    """Query RAGAnything knowledge graph. Returns dict with answer or context."""
    payload = json.dumps({
        "query": query, "mode": mode, "context_only": context_only,
    }).encode()
    req = urllib.request.Request(
        f"{_RAG_URL}/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=_RAG_QUERY_TIMEOUT)
    return json.loads(resp.read().decode())


def _start_pipeline_thread(
    runner: PipelineRunner,
    run_id: str,
    **kwargs,
) -> threading.Thread:
    """Spawn a background pipeline thread and return it."""
    thread = threading.Thread(
        target=_run_pipeline_async,
        args=(runner, run_id),
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()
    return thread


class OrchestratorHandler(BaseHandler):
    """Handler for the Orchestrator service."""

    runner: PipelineRunner | None = None

    def _db_path_required(self) -> str:
        assert self.db_path is not None, "Database path not configured"
        return self.db_path

    def _check_required_deps(self, stage_names: list[str]) -> tuple[bool, list[str]]:
        """Return whether external dependencies needed by stages are healthy."""
        assert self.runner is not None, "PipelineRunner not initialized"
        from services.orchestrator.pipeline import STAGE_EXTERNAL_DEPS

        needed_deps = set()
        for stage_name in stage_names:
            needed_deps.update(STAGE_EXTERNAL_DEPS.get(stage_name, []))

        if not needed_deps:
            return True, []

        ext = self.runner.check_external_health()
        down = []
        for name, info in ext["deps"].items():
            if name not in needed_deps or info["healthy"]:
                continue
            reason = info.get("reason")
            down.append(f"{name} ({reason})" if reason else name)
        return not down, down

    @route("POST", "/run")
    def handle_run(self, data: dict) -> dict | None:
        """Trigger an async pipeline run.

        Returns HTTP 202 immediately with run_id. Poll GET /runs?id=xxx
        for status.

        Request body:
            {
                "query": "abs:\"Kelly criterion\" AND cat:q-fin.*",
                "topic": "limit order book microstructure",
                "paper_id": 42,
                "stages": 5,
                "max_papers": 10,
                "max_formulas": 100,
                "force_parser": "docling",
                "force": false
            }

        All fields optional.
        """
        assert self.runner is not None, "PipelineRunner not initialized"

        query = data.get("query")
        topic = data.get("topic")
        paper_id = data.get("paper_id")
        stages = data.get("stages", 5)
        max_papers = data.get("max_papers", 10)
        max_formulas = data.get("max_formulas", get_default_max_formulas())
        force_parser_raw = data.get("force_parser")
        force = data.get("force", False)
        skip_preflight = data.get("skip_preflight", False)
        try:
            force_parser = normalize_rag_force_parser(force_parser_raw)
        except ValueError as exc:
            self.send_error_json(str(exc), "VALIDATION_ERROR", 400)
            return None

        # Validate
        if paper_id is not None and not isinstance(paper_id, int):
            self.send_error_json(
                "paper_id must be an integer", "VALIDATION_ERROR", 400
            )
            return None
        if topic is not None and not isinstance(topic, str):
            self.send_error_json(
                "topic must be a string", "VALIDATION_ERROR", 400
            )
            return None
        if not 1 <= stages <= 5:
            self.send_error_json(
                "stages must be between 1 and 5", "VALIDATION_ERROR", 400
            )
            return None

        # Preflight: check only the external deps needed by requested stages
        if not skip_preflight:
            stage_list = self.runner._resolve_stages(query, paper_id, stages)
            ok, down = self._check_required_deps(
                [stage_name for stage_name, _ in stage_list]
            )
            if not ok:
                self.send_error_json(
                    f"External dependencies unavailable: {', '.join(down)}",
                    "PREFLIGHT_FAILED",
                    503,
                )
                return None

        run_id = PipelineRunner._generate_run_id()

        logger.info(
            "Pipeline run %s: query=%s paper_id=%s stages=%d (async)",
            run_id, query, paper_id, stages,
        )

        _start_pipeline_thread(
            self.runner,
            run_id,
            query=query,
            topic=topic,
            paper_id=paper_id,
            stages=stages,
            max_papers=max_papers,
            max_formulas=max_formulas,
            force_parser=force_parser,
            force=force,
        )

        # Return 202 Accepted immediately
        self.send_json(
            {"run_id": run_id, "status": "running"},
            status=202,
        )
        return None  # Already sent response

    @route("POST", "/runs/requeue")
    def handle_requeue_runs(self, data: dict) -> dict | None:
        """Create one or more derived runs from failed or partial runs."""
        assert self.runner is not None, "PipelineRunner not initialized"

        run_ids_raw = data.get("run_ids")
        run_id = data.get("run_id")
        if run_id is not None and run_ids_raw is not None:
            self.send_error_json(
                "Provide either run_id or run_ids, not both",
                "VALIDATION_ERROR",
                400,
            )
            return None

        if run_id is not None:
            run_ids = [run_id]
        elif isinstance(run_ids_raw, list):
            run_ids = run_ids_raw
        else:
            self.send_error_json(
                "run_id or run_ids is required",
                "VALIDATION_ERROR",
                400,
            )
            return None

        if not run_ids or not all(isinstance(item, str) and item.strip() for item in run_ids):
            self.send_error_json(
                "run_ids must contain one or more non-empty strings",
                "VALIDATION_ERROR",
                400,
            )
            return None

        stages = data.get("stages")
        max_papers = data.get("max_papers")
        max_formulas = data.get("max_formulas")
        strategy = data.get("strategy", "auto")
        force = data.get("force")
        dry_run = data.get("dry_run", False)
        skip_preflight = data.get("skip_preflight", False)

        if stages is not None and (not isinstance(stages, int) or not 1 <= stages <= 5):
            self.send_error_json(
                "stages must be between 1 and 5",
                "VALIDATION_ERROR",
                400,
            )
            return None
        if max_papers is not None and (
            not isinstance(max_papers, int) or not 1 <= max_papers <= 100
        ):
            self.send_error_json(
                "max_papers must be an integer between 1 and 100",
                "VALIDATION_ERROR",
                400,
            )
            return None
        if max_formulas is not None and (
            not isinstance(max_formulas, int) or not 1 <= max_formulas <= 1000
        ):
            self.send_error_json(
                "max_formulas must be an integer between 1 and 1000",
                "VALIDATION_ERROR",
                400,
            )
            return None
        if not isinstance(strategy, str):
            self.send_error_json(
                "strategy must be a string",
                "VALIDATION_ERROR",
                400,
            )
            return None
        if force is not None and not isinstance(force, bool):
            self.send_error_json(
                "force must be a boolean when provided",
                "VALIDATION_ERROR",
                400,
            )
            return None
        if not isinstance(dry_run, bool):
            self.send_error_json(
                "dry_run must be a boolean",
                "VALIDATION_ERROR",
                400,
            )
            return None

        plans: list[dict] = []
        rejected: list[dict] = []
        for source_run_id in run_ids:
            try:
                plans.append(
                    self.runner.build_requeue_plan(
                        source_run_id,
                        strategy=strategy,
                        stages=stages,
                        max_papers=max_papers,
                        max_formulas=max_formulas,
                        force=force,
                    )
                )
            except RequeueError as exc:
                rejected.append(
                    {
                        "source_run_id": source_run_id,
                        "error": str(exc),
                        "code": exc.code,
                        "status": exc.status,
                    }
                )

        if not plans:
            status = max((item["status"] for item in rejected), default=409)
            self.send_error_json(
                rejected[0]["error"] if rejected else "No runs eligible for requeue",
                rejected[0]["code"] if rejected else "RUN_NOT_REQUEUEABLE",
                status,
                details={"rejected": rejected},
            )
            return None

        if not skip_preflight:
            stage_names = sorted(
                {stage_name for plan in plans for stage_name in plan["stage_names"]}
            )
            ok, down = self._check_required_deps(stage_names)
            if not ok:
                self.send_error_json(
                    f"External dependencies unavailable: {', '.join(down)}",
                    "PREFLIGHT_FAILED",
                    503,
                    details={"rejected": rejected},
                )
                return None

        queued = [
            {
                "source_run_id": plan["source_run_id"],
                "run_id": plan["new_run_id"],
                "strategy": plan["strategy"],
                "stages": plan["stages"],
                "stage_names": plan["stage_names"],
            }
            for plan in plans
        ]

        if dry_run:
            self.send_json(
                {
                    "status": "dry_run",
                    "accepted": len(queued),
                    "rejected": len(rejected),
                    "queued": queued,
                    "errors": rejected,
                }
            )
            return None

        for plan in plans:
            requeue_params = plan["params"]
            _start_pipeline_thread(
                self.runner,
                plan["new_run_id"],
                query=requeue_params.get("query"),
                topic=requeue_params.get("topic"),
                paper_id=requeue_params.get("paper_id"),
                stages=plan["stages"],
                max_papers=requeue_params.get("max_papers", 10),
                max_formulas=requeue_params.get(
                    "max_formulas", get_default_max_formulas()
                ),
                force=requeue_params.get("force", False),
                extra_params={
                    "requeue_of": requeue_params.get("requeue_of"),
                    "requeue_strategy": requeue_params.get("requeue_strategy"),
                    "requeue_source_status": requeue_params.get(
                        "requeue_source_status"
                    ),
                    "requeue_requested_at": requeue_params.get(
                        "requeue_requested_at"
                    ),
                    "requeue_source_stages_completed": requeue_params.get(
                        "requeue_source_stages_completed"
                    ),
                    "requeue_source_stages_requested": requeue_params.get(
                        "requeue_source_stages_requested"
                    ),
                    "requeue_source_failed_stage": requeue_params.get(
                        "requeue_source_failed_stage"
                    ),
                },
            )

        self.send_json(
            {
                "status": "accepted",
                "accepted": len(queued),
                "rejected": len(rejected),
                "queued": queued,
                "errors": rejected,
            },
            status=202,
        )
        return None

    @route("GET", "/status")
    def handle_status(self) -> dict:
        """Get aggregate pipeline status."""
        assert self.runner is not None, "PipelineRunner not initialized"

        status = self.runner.get_pipeline_status()

        # Add cron info
        cron_enabled = os.environ.get(
            "RP_ORCHESTRATOR_CRON_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        cron_expr = os.environ.get("RP_ORCHESTRATOR_CRON", "0 8 * * *")

        status["cron"] = {
            "enabled": cron_enabled,
            "schedule": cron_expr,
        }

        return status

    @route("GET", "/status/services")
    def handle_services_status(self) -> dict:
        """Check health of all downstream services."""
        assert self.runner is not None, "PipelineRunner not initialized"
        return self.runner.get_services_health()

    # -- Query endpoints for reading pipeline data --

    def _query_params(self) -> dict[str, str]:
        """Parse query string from self.path into {key: value} dict."""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        raw = parse_qs(qs, keep_blank_values=False)
        return {k: v[0] for k, v in raw.items()}

    @route("GET", "/papers")
    def handle_papers(self) -> dict | list | None:
        """Query papers from the pipeline database.

        GET /papers?stage=analyzed&limit=50  → list papers
        GET /papers?id=42                    → single paper with formulas,
                                               validations, and generated code
        """
        params = self._query_params()
        paper_id = params.get("id")

        if paper_id is not None:
            return self._get_paper_detail(int(paper_id))

        stage = params.get("stage")
        limit = min(int(params.get("limit", "50")), 200)
        return self._list_papers(stage=stage, limit=limit)

    @route("GET", "/formulas")
    def handle_formulas(self) -> list | None:
        """Query formulas from the pipeline database.

        GET /formulas?paper_id=42&stage=validated&limit=50
        """
        params = self._query_params()
        paper_id = params.get("paper_id")
        stage = params.get("stage")
        limit = min(int(params.get("limit", "50")), 200)

        clauses = []
        bind: list = []
        if paper_id is not None:
            clauses.append("f.paper_id = ?")
            bind.append(int(paper_id))
        if stage:
            clauses.append("f.stage = ?")
            bind.append(stage)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                f"SELECT f.* FROM formulas f {where} "  # noqa: S608
                f"ORDER BY f.id DESC LIMIT ?",
                [*bind, limit],
            ).fetchall()
        return [Formula(**dict(r)).model_dump(mode="json") for r in rows]

    @route("GET", "/generated-code")
    def handle_generated_code(self) -> list | None:
        """Query generated code from the pipeline database.

        GET /generated-code?paper_id=42                         # All code for paper
        GET /generated-code?paper_id=42&language=python         # Filter by language
        GET /generated-code?paper_id=42&formula_id=551          # Specific formula
        GET /generated-code?paper_id=42&limit=50&offset=0       # Pagination
        """
        params = self._query_params()
        paper_id = params.get("paper_id")

        if paper_id is None:
            self.send_error_json(
                "paper_id query parameter is required",
                "VALIDATION_ERROR", 400,
            )
            return None

        language = params.get("language")
        formula_id = params.get("formula_id")
        limit = min(int(params.get("limit", "50")), 200)
        offset = int(params.get("offset", "0"))

        clauses = ["f.paper_id = ?"]
        bind: list = [int(paper_id)]

        if language:
            clauses.append("g.language = ?")
            bind.append(language)
        if formula_id:
            clauses.append("g.formula_id = ?")
            bind.append(int(formula_id))

        where = "WHERE " + " AND ".join(clauses)

        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                f"SELECT g.*, f.latex, f.description "  # noqa: S608
                f"FROM generated_code g "
                f"JOIN formulas f ON f.id = g.formula_id "
                f"{where} ORDER BY g.id LIMIT ? OFFSET ?",
                [*bind, limit, offset],
            ).fetchall()
        return [dict(r) for r in rows]

    @route("GET", "/runs")
    def handle_runs(self) -> dict | list | None:
        """Query pipeline runs.

        GET /runs                    # List recent runs
        GET /runs?id=run-xxx         # Single run by ID
        GET /runs?limit=10           # Custom limit
        """
        assert self.runner is not None, "PipelineRunner not initialized"
        params = self._query_params()
        run_id = params.get("id")

        if run_id:
            result = self.runner.get_run_status(run_id)
            if result is None:
                self.send_error_json(
                    f"Run {run_id} not found", "NOT_FOUND", 404
                )
                return None
            return result

        limit = min(int(params.get("limit", "20")), 100)
        return self.runner.list_runs(limit=limit)

    # -- GitHub Discovery endpoints --

    @route("POST", "/search-github")
    def handle_search_github(self, data: dict) -> dict | None:
        """Search GitHub for implementations of a paper.

        Request body:
            {
                "paper_id": 42,
                "max_repos": 3,
                "languages": ["python", "rust", "cpp"],
                "min_stars": 5,
                "query_override": null,
                "force": false
            }

        Only paper_id is required.
        """
        paper_id = data.get("paper_id")
        if paper_id is None or not isinstance(paper_id, int):
            self.send_error_json(
                "paper_id is required and must be an integer",
                "VALIDATION_ERROR", 400,
            )
            return None

        logger.info("GitHub search: paper_id=%d", paper_id)

        result = search_and_analyze(
            paper_id=paper_id,
            db_path=self._db_path_required(),
            max_repos=data.get("max_repos"),
            languages=data.get("languages"),
            min_stars=data.get("min_stars"),
            query_override=data.get("query_override"),
            force=data.get("force", False),
        )

        return result

    @route("GET", "/github-repos")
    def handle_github_repos(self) -> list | None:
        """Query GitHub repos and their analyses.

        GET /github-repos?paper_id=42&recommendation=USE&limit=50
        """
        params = self._query_params()
        paper_id = params.get("paper_id")

        if paper_id is None:
            self.send_error_json(
                "paper_id query parameter is required",
                "VALIDATION_ERROR", 400,
            )
            return None

        recommendation = params.get("recommendation")
        limit = min(int(params.get("limit", "50")), 200)

        clauses = ["r.paper_id = ?"]
        bind: list = [int(paper_id)]

        if recommendation:
            clauses.append("a.recommendation = ?")
            bind.append(recommendation.upper())

        where = "WHERE " + " AND ".join(clauses)

        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                f"SELECT r.*, a.relevance_score, a.quality_score, "  # noqa: S608
                f"a.formula_matches, a.summary, a.recommendation, "
                f"a.key_files, a.dependencies, a.model_used, "
                f"a.analysis_time_ms, a.error as analysis_error, "
                f"a.id as analysis_id "
                f"FROM github_repos r "
                f"LEFT JOIN github_analyses a ON a.repo_id = r.id "
                f"{where} ORDER BY r.stars DESC LIMIT ?",
                [*bind, limit],
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            repo = GitHubRepo(
                id=d["id"],
                paper_id=d["paper_id"],
                full_name=d["full_name"],
                url=d["url"],
                clone_url=d["clone_url"],
                description=d.get("description"),
                stars=d.get("stars", 0),
                language=d.get("language"),
                updated_at=d.get("updated_at"),
                topics=d.get("topics", "[]"),
                search_query=d.get("search_query"),
                created_at=d.get("created_at"),
            )
            analysis = None
            if d.get("analysis_id"):
                analysis = GitHubAnalysis(
                    id=d["analysis_id"],
                    repo_id=d["id"],
                    relevance_score=d.get("relevance_score"),
                    quality_score=d.get("quality_score"),
                    formula_matches=d.get("formula_matches", "[]"),
                    summary=d.get("summary"),
                    recommendation=d.get("recommendation"),
                    key_files=d.get("key_files", "[]"),
                    dependencies=d.get("dependencies", "[]"),
                    model_used=d.get("model_used"),
                    analysis_time_ms=d.get("analysis_time_ms"),
                    error=d.get("analysis_error"),
                )
            results.append({
                "repo": repo.model_dump(mode="json"),
                "analysis": analysis.model_dump(mode="json") if analysis else None,
            })

        return results

    # -- Semantic search endpoint --

    @route("POST", "/search")
    def handle_search(self, data: dict) -> dict | None:
        """Semantic search across all processed papers via RAGAnything.

        Request body:
            {
                "query": "Kelly criterion stochastic volatility",
                "mode": "hybrid",
                "context_only": false
            }

        Mode options: hybrid, local, global, mix, naive, bypass.
        context_only: if true, returns raw context chunks without LLM synthesis (fast, <2s).
        Falls back to SQLite substring match if RAGAnything is unavailable.
        """
        query = data.get("query", "").strip()
        if not query:
            self.send_error_json(
                "query is required", "VALIDATION_ERROR", 400
            )
            return None

        mode = data.get("mode", "hybrid")
        context_only = data.get("context_only", False)
        start = time.time()

        try:
            rag_result = _query_rag(query, mode, context_only=context_only)
        except Exception as e:
            logger.warning("RAG query failed, falling back to SQLite: %s", e)
            return self._search_fallback(query)

        elapsed_ms = int((time.time() - start) * 1000)

        result = {
            "success": rag_result.get("success", False),
            "query": query,
            "mode": mode,
            "context_only": context_only,
            "time_ms": elapsed_ms,
        }
        if context_only:
            result["context"] = rag_result.get("context", "")
        else:
            result["answer"] = rag_result.get("answer", "")
        return result

    @route("POST", "/notations")
    def handle_add_notation(self, data: dict) -> dict | None:
        """Add or update a custom LaTeX notation (upsert)."""
        name = data.get("name", "").strip()
        body = data.get("body", "").strip()
        nargs = data.get("nargs", 0)
        description = data.get("description", "")

        if not name or not body:
            self.send_error_json(
                "name and body are required", "VALIDATION_ERROR", 400
            )
            return None
        if not 0 <= nargs <= 9:
            self.send_error_json(
                "nargs must be 0-9", "VALIDATION_ERROR", 400
            )
            return None

        with transaction(self._db_path_required()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_notations "
                "(name, body, nargs, description, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (name, body, nargs, description),
            )
        return {"success": True, "name": name, "action": "upserted"}

    @route("GET", "/notations")
    def handle_list_notations(self) -> list:
        """List all custom LaTeX notations."""
        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                "SELECT * FROM custom_notations ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    @route("POST", "/notations/delete")
    def handle_delete_notation(self, data: dict) -> dict | None:
        """Delete a custom LaTeX notation."""
        name = data.get("name", "").strip()
        if not name:
            self.send_error_json(
                "name is required", "VALIDATION_ERROR", 400
            )
            return None

        with transaction(self._db_path_required()) as conn:
            cursor = conn.execute(
                "DELETE FROM custom_notations WHERE name = ?", (name,)
            )
        if cursor.rowcount == 0:
            self.send_error_json(
                f"Notation '{name}' not found", "NOT_FOUND", 404
            )
            return None
        return {"success": True, "name": name, "action": "deleted"}

    def _search_fallback(self, query: str) -> dict:
        """Fallback: substring match on title/abstract in SQLite."""
        terms = query.lower().split()
        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC LIMIT 200"
            ).fetchall()

        matches = []
        for row in rows:
            text = f"{row['title']} {row['abstract'] or ''}".lower()
            if any(t in text for t in terms):
                matches.append(
                    Paper(**dict(row)).model_dump(mode="json")
                )

        return {
            "success": True,
            "query": query,
            "mode": "fallback",
            "answer": None,
            "papers": matches[:20],
            "time_ms": 0,
        }

    # -- Helpers for paper queries --

    def _list_papers(
        self, *, stage: str | None = None, limit: int = 50
    ) -> list[dict]:
        clauses = []
        bind: list = []
        if stage:
            clauses.append("p.stage = ?")
            bind.append(stage)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with transaction(self._db_path_required()) as conn:
            rows = conn.execute(
                f"SELECT p.* FROM papers p {where} "  # noqa: S608
                f"ORDER BY p.created_at DESC LIMIT ?",
                [*bind, limit],
            ).fetchall()
        return [Paper(**dict(r)).model_dump(mode="json") for r in rows]

    def _get_paper_detail(self, paper_id: int) -> dict | None:
        with transaction(self._db_path_required()) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?", [paper_id]
            ).fetchone()
            if row is None:
                self.send_error_json(
                    f"Paper {paper_id} not found", "NOT_FOUND", 404
                )
                return None

            paper = Paper(**dict(row)).model_dump(mode="json")

            # Formulas for this paper
            f_rows = conn.execute(
                "SELECT * FROM formulas WHERE paper_id = ? ORDER BY id",
                [paper_id],
            ).fetchall()
            formulas = []
            for fr in f_rows:
                formula = Formula(**dict(fr)).model_dump(mode="json")

                # Validations for this formula
                v_rows = conn.execute(
                    "SELECT * FROM validations WHERE formula_id = ? "
                    "ORDER BY id",
                    [fr["id"]],
                ).fetchall()
                formula["validations"] = [dict(vr) for vr in v_rows]

                # Generated code for this formula
                gc_rows = conn.execute(
                    "SELECT * FROM generated_code WHERE formula_id = ? "
                    "ORDER BY id",
                    [fr["id"]],
                ).fetchall()
                formula["generated_code"] = [dict(gcr) for gcr in gc_rows]

                formulas.append(formula)

            paper["formulas"] = formulas
        return paper


def _run_pipeline_async(runner: PipelineRunner, run_id: str, **kwargs) -> None:
    """Thread target for async pipeline execution."""
    try:
        result = runner.run(run_id=run_id, **kwargs)
        notify_pipeline_result(result)
    except Exception:
        logger.exception("Async pipeline run %s failed", run_id)
        notify("[FAIL] Research Pipeline", f"Run {run_id} crashed")


def _cron_run() -> None:
    """Executed by APScheduler on each cron trigger."""
    runner = OrchestratorHandler.runner
    if runner is None:
        logger.error("Cron trigger but PipelineRunner not initialized")
        return

    query = os.environ.get(
        "RP_ORCHESTRATOR_DEFAULT_QUERY",
        'abs:"Kelly criterion" AND cat:q-fin.*',
    )
    stages = int(os.environ.get("RP_ORCHESTRATOR_STAGES_PER_RUN", "5"))
    max_papers = int(os.environ.get("RP_ORCHESTRATOR_CRON_MAX_PAPERS", "10"))
    max_formulas = int(
        os.environ.get(
            "RP_ORCHESTRATOR_CRON_MAX_FORMULAS",
            str(get_default_max_formulas()),
        )
    )

    logger.info("Cron run starting: query=%s stages=%d", query, stages)
    start = time.time()

    try:
        result = runner.run(
            query=query,
            stages=stages,
            max_papers=max_papers,
            max_formulas=max_formulas,
        )
        elapsed = int((time.time() - start) * 1000)
        logger.info(
            "Cron run complete: status=%s stages=%d/%d time=%dms",
            result["status"],
            result["stages_completed"],
            result["stages_requested"],
            elapsed,
        )
        notify_pipeline_result(result)
    except Exception:
        logger.exception("Cron run failed")
        notify("[FAIL] Research Pipeline", "Cron run crashed")


def main() -> None:
    """Start the Orchestrator service."""
    config = load_config("orchestrator")
    init_db(config.db_path)

    # Initialize pipeline runner
    runner = PipelineRunner(config.db_path)
    OrchestratorHandler.runner = runner

    resume_stuck_runs = os.environ.get(
        "RP_ORCHESTRATOR_RESUME_STUCK_RUNS", "true"
    ).lower() in ("true", "1", "yes")
    if resume_stuck_runs:
        resumed, failed = _resume_stuck_runs(runner)
        if resumed:
            logger.warning(
                "Resumed %d orphaned pipeline run(s) from previous crash",
                resumed,
            )
        if failed:
            logger.warning(
                "Failed to resume %d orphaned pipeline run(s); marked failed",
                failed,
            )
    else:
        # Clean up stuck pipeline runs from previous crashes
        cleaned = runner.cleanup_stuck_runs()
        if cleaned:
            logger.warning(
                "Cleaned %d stuck pipeline run(s) from previous crash",
                cleaned,
            )

    # Create scheduler (if enabled)
    scheduler = create_scheduler(_cron_run)

    if scheduler:
        scheduler.start()
        logger.info("Cron scheduler started")

    # Start HTTP server (blocking)
    service = BaseService(
        "orchestrator", config.port, OrchestratorHandler, str(config.db_path)
    )

    try:
        service.run()
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("Cron scheduler stopped")


if __name__ == "__main__":
    main()
