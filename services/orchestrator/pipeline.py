"""Pipeline execution engine — stage dispatch, retry, and status tracking.

Coordinates the 5 downstream services (Discovery → Analyzer → Extractor →
Validator → Codegen) via HTTP calls to their /process endpoints.

Environment:
    RP_ORCHESTRATOR_RETRY_MAX=3             # Max retries per service call
    RP_ORCHESTRATOR_RETRY_BACKOFF=4.0       # Backoff base (seconds)
    RP_ORCHESTRATOR_TIMEOUT=300             # Default request timeout (seconds)
    RP_ORCHESTRATOR_CODEGEN_TIMEOUT=900     # Codegen-specific timeout (seconds)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from shared.config import resolve_localhost_url
from shared.db import transaction

from services.orchestrator.metrics import (
    FORMULAS_VALIDATED,
    PAPERS_PROCESSED,
    PIPELINE_RUN_DURATION,
    PIPELINE_RUNS_ACTIVE,
    STAGE_COMPLETED,
    STAGE_DURATION,
)

logger = logging.getLogger(__name__)


class RequeueError(Exception):
    """Raised when a historical run cannot be safely requeued."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "REQUEUE_ERROR",
        status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

def _stage_port(service: str, default: int) -> int:
    raw = os.environ.get(f"RP_{service.upper()}_PORT", str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _stage_url(service: str, port: int) -> str:
    explicit = os.environ.get(f"RP_{service.upper()}_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://localhost:{port}"


# Stage order: (name, port)
STAGE_ORDER: list[tuple[str, int]] = [
    ("discovery", _stage_port("discovery", 8770)),
    ("analyzer", _stage_port("analyzer", 8771)),
    ("extractor", _stage_port("extractor", 8772)),
    ("validator", _stage_port("validator", 8773)),
    ("codegen", _stage_port("codegen", 8774)),
]

# External dependencies checked before pipeline runs: (name, base_url, health_path)
EXTERNAL_DEPS: list[tuple[str, str, str]] = [
    (
        "cas",
        resolve_localhost_url(
            os.environ.get("RP_VALIDATOR_CAS_URL", "http://localhost:8769")
        ),
        "/health",
    ),
    (
        "rag",
        resolve_localhost_url(
            os.environ.get("RP_EXTRACTOR_RAG_URL", "http://localhost:8767")
        ),
        "/health",
    ),
    (
        "ollama",
        resolve_localhost_url(
            os.environ.get("RP_CODEGEN_OLLAMA_URL", "http://localhost:11434")
        ),
        "/",
    ),
]

EXTERNAL_UNHEALTHY_REASONS: dict[str, str] = {
    "cas_no_engines": "no_engines_available",
    "rag_circuit_open": "circuit_breaker_open",
}

# Which stages require which external deps (hard dependencies only).
# Ollama is excluded: codegen uses it as last-resort fallback in the LLM chain,
# not as a hard requirement.
STAGE_EXTERNAL_DEPS: dict[str, list[str]] = {
    "extractor": ["rag"],
    "validator": ["cas"],
}

# Maps orchestrator params to per-service params
STAGE_PARAMS: dict[str, dict[str, str]] = {
    "discovery": {"query": "query", "max_papers": "max_results"},
    "analyzer": {
        "paper_id": "paper_id",
        "max_papers": "max_papers",
        "force": "force",
    },
    "extractor": {"paper_id": "paper_id", "max_papers": "max_papers", "force": "force"},
    "validator": {
        "paper_id": "paper_id",
        "max_formulas": "max_formulas",
        "force": "force",
    },
    "codegen": {
        "paper_id": "paper_id",
        "max_formulas": "max_formulas",
        "force": "force",
    },
}


# Maps DB stage name to the index in STAGE_ORDER that produced it
DB_STAGE_INDEX: dict[str, int] = {
    "discovered": 0,  # After discovery (idx 0)
    "analyzed": 1,    # After analyzer (idx 1)
    "extracted": 2,   # After extractor (idx 2)
    "validated": 3,   # After validator (idx 3)
    "codegen": 4,     # After codegen (idx 4)
}


class PipelineRunner:
    """Executes pipeline stages sequentially with retry logic."""

    # Per-stage timeout overrides (seconds).
    # Analyzer can legitimately take much longer than the default 300s because it
    # performs sequential LLM scoring across a batch of papers.
    # Codegen likewise processes formulas sequentially and needs a longer timeout.
    STAGE_TIMEOUTS: dict[str, int] = {
        "analyzer": int(os.environ.get("RP_ORCHESTRATOR_ANALYZER_TIMEOUT", "1800")),
        "codegen": int(os.environ.get("RP_ORCHESTRATOR_CODEGEN_TIMEOUT", "900")),
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.timeout = int(os.environ.get("RP_ORCHESTRATOR_TIMEOUT", "300"))
        self.retry_max = int(os.environ.get("RP_ORCHESTRATOR_RETRY_MAX", "3"))
        self.retry_backoff = float(
            os.environ.get("RP_ORCHESTRATOR_RETRY_BACKOFF", "4.0")
        )
        # Keep per-instance overrides so tests and env patches are predictable.
        self.STAGE_TIMEOUTS = {
            "analyzer": int(
                os.environ.get("RP_ORCHESTRATOR_ANALYZER_TIMEOUT", "1800")
            ),
            "codegen": int(
                os.environ.get("RP_ORCHESTRATOR_CODEGEN_TIMEOUT", "900")
            ),
        }

    def run(
        self,
        query: str | None = None,
        topic: str | None = None,
        paper_id: int | None = None,
        stages: int = 5,
        max_papers: int = 10,
        max_formulas: int = 50,
        force: bool = False,
        run_id: str | None = None,
        extra_params: dict | None = None,
    ) -> dict:
        """Execute a pipeline run.

        Args:
            query: arXiv search query (triggers Discovery).
            paper_id: Advance specific paper.
            stages: How many stages to advance (1-5).
            max_papers: Max papers per batch.
            max_formulas: Max formulas per batch.
            force: Reprocess already-processed items.
            run_id: Pre-generated run ID (for async runs).

        Returns:
            Run result dict with run_id, status, results, errors.
        """
        if run_id is None:
            run_id = self._generate_run_id()
        start = time.time()
        PIPELINE_RUNS_ACTIVE.inc()

        params = {
            "query": query,
            "topic": topic,
            "paper_id": paper_id,
            "max_papers": max_papers,
            "max_formulas": max_formulas,
            "force": force,
        }
        if extra_params:
            params.update(extra_params)

        # Determine which stages to run
        stage_list = self._resolve_stages(query, paper_id, stages)

        # Persist run record
        try:
            self._create_run_record(run_id, params, len(stage_list))
        except Exception:
            logger.debug("pipeline_runs table not available, skipping persistence")

        results: dict[str, dict] = {}
        errors: list[str] = []
        stages_completed = 0
        stages_skipped: list[str] = []
        has_failure = False
        scoped_run = query is not None or paper_id is not None
        blocked_by_stage: str | None = None

        # Stages that process formulas in batches need iteration
        BATCH_STAGES = {"validator", "codegen"}
        MAX_BATCH_ITERATIONS = 100

        try:
            for stage_name, port in stage_list:
                if blocked_by_stage is not None:
                    logger.info(
                        "Skipping stage %s: upstream stage %s failed",
                        stage_name,
                        blocked_by_stage,
                    )
                    results[stage_name] = {
                        "status": "skipped",
                        "reason": f"upstream_failed:{blocked_by_stage}",
                        "upstream_stage": blocked_by_stage,
                        "time_ms": 0,
                    }
                    stages_skipped.append(stage_name)
                    STAGE_COMPLETED.labels(stage=stage_name, result="skipped").inc()
                    continue

                stage_params = self._build_stage_params(stage_name, params)

                if not stage_params:
                    # Skip stages with no applicable params (e.g., Discovery without query)
                    logger.info("Skipping %s: no applicable params", stage_name)
                    STAGE_COMPLETED.labels(stage=stage_name, result="skipped").inc()
                    continue

                logger.info("Dispatching stage: %s (port %d)", stage_name, port)
                stage_start = time.time()
                stage_base_url = _stage_url(stage_name, port)

                stage_timeout = self.STAGE_TIMEOUTS.get(stage_name, self.timeout)
                try:
                    retry_on_timeout = stage_name != "analyzer"
                    if stage_name in BATCH_STAGES:
                        # Iterate until all formulas are processed
                        batch_results: list[dict] = []
                        for iteration in range(1, MAX_BATCH_ITERATIONS + 1):
                            result = self._call_service_with_retry(
                                f"{stage_base_url}/process", stage_params,
                                timeout=stage_timeout,
                                retry_on_timeout=retry_on_timeout,
                            )
                            batch_results.append(result)
                            processed = result.get("formulas_processed", 0)
                            if processed == 0:
                                break
                            logger.info(
                                "Stage %s iteration %d: %d formulas processed",
                                stage_name, iteration, processed,
                            )
                        # Merge batch results
                        result = self._merge_batch_results(batch_results, stage_name)
                    else:
                        result = self._call_service_with_retry(
                            f"{stage_base_url}/process", stage_params,
                            timeout=stage_timeout,
                            retry_on_timeout=retry_on_timeout,
                        )

                    stage_duration = time.time() - stage_start
                    stage_ms = int(stage_duration * 1000)
                    result["time_ms"] = stage_ms
                    results[stage_name] = result
                    stages_completed += 1
                    STAGE_DURATION.labels(stage=stage_name).observe(stage_duration)
                    STAGE_COMPLETED.labels(stage=stage_name, result="success").inc()
                    logger.info(
                        "Stage %s completed in %dms", stage_name, stage_ms
                    )
                except ServiceError as e:
                    stage_duration = time.time() - stage_start
                    stage_ms = int(stage_duration * 1000)
                    error_msg = f"{stage_name}: {e}"
                    errors.append(error_msg)
                    results[stage_name] = {
                        "status": "failed",
                        "error": str(e),
                        "time_ms": stage_ms,
                    }
                    has_failure = True
                    STAGE_DURATION.labels(stage=stage_name).observe(stage_duration)
                    STAGE_COMPLETED.labels(stage=stage_name, result="failure").inc()
                    logger.error("Stage %s failed: %s", stage_name, e)
                    # For query/paper-scoped runs, downstream stages depend on this
                    # stage's output. Mark them skipped instead of reporting false
                    # progress like 4/5 after analyzer failure.
                    if scoped_run:
                        blocked_by_stage = stage_name
                    # For unscoped backlog runs, continue — later stages may still
                    # process already-eligible items from the global DB.

            # Extract paper/formula counts from stage results for Prometheus
            papers_found = results.get("discovery", {}).get("papers_found", 0)
            if papers_found:
                PAPERS_PROCESSED.inc(papers_found)

            formulas_processed = results.get("validator", {}).get(
                "formulas_processed", 0
            )
            if formulas_processed:
                FORMULAS_VALIDATED.inc(formulas_processed)

        finally:
            elapsed = time.time() - start
            PIPELINE_RUN_DURATION.observe(elapsed)
            PIPELINE_RUNS_ACTIVE.dec()

        elapsed_ms = int(elapsed * 1000)

        status = "completed"
        if has_failure:
            status = "partial" if stages_completed > 0 else "failed"

        run_result = {
            "run_id": run_id,
            "status": status,
            "stages_completed": stages_completed,
            "stages_requested": len(stage_list),
            "stages_skipped": len(stages_skipped),
            "skipped_stages": stages_skipped,
            "results": results,
            "errors": errors,
            "time_ms": elapsed_ms,
        }

        # Persist final results
        try:
            self._update_run_record(run_id, run_result)
        except Exception:
            logger.debug("pipeline_runs update failed, skipping persistence")

        return run_result

    def _resolve_stages(
        self,
        query: str | None,
        paper_id: int | None,
        stages: int,
    ) -> list[tuple[str, int]]:
        """Determine which stages to execute.

        Args:
            query: If provided, start from Discovery.
            paper_id: If provided, start from paper's current stage + 1.
            stages: Max number of stages to run.

        Returns:
            List of (stage_name, port) tuples to execute.
        """
        stages = max(1, min(stages, 5))

        if query:
            # Full pipeline from Discovery
            return STAGE_ORDER[:stages]

        if paper_id:
            # Determine paper's current stage and start from next
            current = self._get_paper_stage(paper_id)

            if current in ("rejected", "failed"):
                return []  # Can't advance rejected/failed papers

            # Map DB stage names to STAGE_ORDER index (after which service)
            idx = DB_STAGE_INDEX.get(current, -1) + 1

            return STAGE_ORDER[idx : idx + stages]

        # Batch mode: run all stages
        return STAGE_ORDER[:stages]

    @staticmethod
    def _merge_batch_results(
        batch_results: list[dict], stage_name: str
    ) -> dict:
        """Merge multiple batch iteration results into a single result.

        Sums numeric counters and concatenates error lists.
        """
        if not batch_results:
            return {"success": True, "service": stage_name, "formulas_processed": 0}

        merged = dict(batch_results[0])
        merged["batch_iterations"] = len(batch_results)

        if len(batch_results) == 1:
            return merged

        for r in batch_results[1:]:
            merged["formulas_processed"] = (
                merged.get("formulas_processed", 0)
                + r.get("formulas_processed", 0)
            )
            # Merge stage-specific counters
            for key in ("formulas_valid", "formulas_invalid", "formulas_partial",
                        "formulas_unparseable", "formulas_failed",
                        "explanations_generated"):
                if key in r:
                    merged[key] = merged.get(key, 0) + r[key]
            # Merge code_generated dict (codegen stage)
            if "code_generated" in r and "code_generated" in merged:
                for lang, count in r["code_generated"].items():
                    merged["code_generated"][lang] = (
                        merged["code_generated"].get(lang, 0) + count
                    )
            # Merge errors
            merged.setdefault("errors", []).extend(r.get("errors", []))

        return merged

    def _build_stage_params(
        self, stage_name: str, params: dict
    ) -> dict:
        """Build service-specific params from orchestrator params.

        Args:
            stage_name: Target service name.
            params: Orchestrator-level params.

        Returns:
            Service-specific param dict (empty values excluded).
        """
        mapping = STAGE_PARAMS.get(stage_name, {})
        result = {}

        for orch_key, svc_key in mapping.items():
            value = params.get(orch_key)
            if value is not None:
                result[svc_key] = value

        if stage_name == "analyzer":
            topic = params.get("topic") or params.get("query")
            if isinstance(topic, str) and topic.strip():
                result["topic"] = topic

        return result

    def _call_service_with_retry(
        self,
        url: str,
        params: dict,
        *,
        timeout: int | None = None,
        retry_on_timeout: bool = True,
    ) -> dict:
        """Call a service endpoint with exponential backoff retry.

        Args:
            url: Service /process URL.
            params: Request body.
            timeout: Request timeout in seconds (overrides default).
            retry_on_timeout: Whether request timeouts should be retried.

        Returns:
            Parsed JSON response.

        Raises:
            ServiceError: If all retries exhausted.
        """
        effective_timeout = timeout or self.timeout
        last_error: Exception | None = None

        for attempt in range(self.retry_max + 1):
            try:
                resp = requests.post(
                    url, json=params, timeout=effective_timeout
                )

                if resp.status_code < 400:
                    return resp.json()

                if resp.status_code < 500:
                    # Client error — don't retry
                    try:
                        body = resp.json()
                        error_msg = body.get("error", resp.text)
                    except ValueError:
                        error_msg = resp.text
                    raise ServiceError(
                        f"HTTP {resp.status_code}: {error_msg}"
                    )

                # 5xx — retry
                last_error = ServiceError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                )

            except requests.ConnectionError as e:
                last_error = ServiceError(f"Connection refused: {e}")
            except requests.Timeout as e:
                last_error = ServiceError(f"Timeout after {effective_timeout}s: {e}")
                if not retry_on_timeout:
                    break

            if attempt < self.retry_max:
                delay = self.retry_backoff ** attempt  # 1, 4, 16
                logger.warning(
                    "Retry %d/%d for %s in %.0fs: %s",
                    attempt + 1,
                    self.retry_max,
                    url,
                    delay,
                    last_error,
                )
                time.sleep(delay)

        raise last_error or ServiceError(f"Failed after {self.retry_max} retries")

    def _get_paper_stage(self, paper_id: int) -> str:
        """Look up a paper's current pipeline stage.

        Args:
            paper_id: Paper ID.

        Returns:
            Stage string, or "unknown" if not found.
        """
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT stage FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        return row["stage"] if row else "unknown"

    def get_pipeline_status(self) -> dict:
        """Get aggregate pipeline status from the database.

        Returns:
            Dict with papers_by_stage, formulas_by_stage, recent_errors.
        """
        with transaction(self.db_path) as conn:
            # Papers by stage
            rows = conn.execute(
                "SELECT stage, COUNT(*) as cnt FROM papers GROUP BY stage"
            ).fetchall()
            papers_by_stage = {row["stage"]: row["cnt"] for row in rows}

            # Formulas by stage
            rows = conn.execute(
                "SELECT stage, COUNT(*) as cnt FROM formulas GROUP BY stage"
            ).fetchall()
            formulas_by_stage = {row["stage"]: row["cnt"] for row in rows}

            # Recent errors (last 10)
            rows = conn.execute(
                "SELECT id, stage, error, updated_at "
                "FROM papers WHERE error IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
            recent_errors = [
                {
                    "paper_id": row["id"],
                    "stage": row["stage"],
                    "error": row["error"],
                    "timestamp": row["updated_at"],
                }
                for row in rows
            ]

        return {
            "papers_by_stage": papers_by_stage,
            "formulas_by_stage": formulas_by_stage,
            "recent_errors": recent_errors,
        }

    def get_services_health(self) -> dict:
        """Check health of all downstream services.

        Returns:
            Dict with all_healthy flag and per-service status.
        """
        services = {}
        all_healthy = True

        for name, port in STAGE_ORDER:
            health_url = f"{_stage_url(name, port)}/health"
            try:
                resp = requests.get(health_url, timeout=5)
                if resp.status_code == 200:
                    services[name] = resp.json()
                    services[name]["port"] = port
                else:
                    services[name] = {
                        "status": "error",
                        "port": port,
                        "error": f"HTTP {resp.status_code}",
                    }
                    all_healthy = False
            except requests.RequestException as e:
                services[name] = {
                    "status": "error",
                    "port": port,
                    "error": str(e),
                }
                all_healthy = False

        external = self.check_external_health()
        if not external["all_healthy"]:
            all_healthy = False

        return {
            "all_healthy": all_healthy,
            "services": services,
            "external": external,
        }

    def check_external_health(self) -> dict:
        """Check health of external dependencies (CAS, RAG, Ollama).

        Returns:
            Dict with all_healthy flag and per-dep status.
        """
        deps: dict[str, dict] = {}
        all_healthy = True

        for name, base_url, health_path in EXTERNAL_DEPS:
            url = f"{base_url}{health_path}"
            try:
                resp = requests.get(url, timeout=3)
                payload: dict | None = None
                try:
                    data = resp.json()
                    payload = data if isinstance(data, dict) else None
                except ValueError:
                    payload = None

                healthy = resp.status_code < 400
                dep_info: dict[str, object] = {
                    "url": base_url,
                    "healthy": healthy,
                    "status_code": resp.status_code,
                }
                if payload:
                    for field in ("service", "version", "status"):
                        if field in payload:
                            dep_info[field] = payload[field]

                    if name == "cas":
                        dep_info["engines_total"] = payload.get("engines_total")
                        dep_info["engines_available"] = payload.get(
                            "engines_available"
                        )
                        if healthy and payload.get("engines_available", 1) <= 0:
                            dep_info["healthy"] = False
                            dep_info["reason"] = EXTERNAL_UNHEALTHY_REASONS[
                                "cas_no_engines"
                            ]
                    elif name == "rag":
                        circuit_breaker = payload.get("circuit_breaker")
                        if isinstance(circuit_breaker, dict):
                            dep_info["circuit_breaker"] = circuit_breaker
                            if (
                                healthy
                                and circuit_breaker.get("state") == "open"
                            ):
                                dep_info["healthy"] = False
                                dep_info["reason"] = EXTERNAL_UNHEALTHY_REASONS[
                                    "rag_circuit_open"
                                ]

                healthy = bool(dep_info["healthy"])
            except requests.RequestException as e:
                healthy = False
                dep_info = {
                    "url": base_url,
                    "healthy": False,
                    "error": str(e),
                }

            deps[name] = dep_info
            if not healthy:
                all_healthy = False

        return {"all_healthy": all_healthy, "deps": deps}

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a unique run ID.

        Format: run-YYYYMMDD-HHMMSS-XXXXXX
        """
        now = datetime.now(timezone.utc)
        short_id = uuid.uuid4().hex[:6]
        return f"run-{now.strftime('%Y%m%d-%H%M%S')}-{short_id}"


    def cleanup_stuck_runs(self) -> int:
        """Mark all 'running' pipeline runs as 'failed' on startup.

        At process startup, any run still in 'running' state is orphaned
        (the previous process crashed or was killed). We mark them all as
        failed unconditionally — there is no surviving thread to complete them.

        Returns:
            Number of runs marked as failed.
        """
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT run_id FROM pipeline_runs WHERE status = 'running'"
            ).fetchall()
            if not rows:
                return 0
            run_ids = [r["run_id"] for r in rows]
            error_json = json.dumps(
                ["Marked as failed: orphaned in running state at service restart"]
            )
            conn.execute(
                "UPDATE pipeline_runs SET status = 'failed', "
                "errors = ?, completed_at = datetime('now') "
                "WHERE status = 'running'",
                (error_json,),
            )
        for rid in run_ids:
            logger.warning("Cleaned stuck pipeline run: %s", rid)
        return len(run_ids)

    def get_stuck_runs(self) -> list[dict]:
        """Return pipeline_runs rows still marked as running.

        These runs are orphaned after an orchestrator restart. Callers can
        either resume them asynchronously or mark them failed.
        """
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT run_id, params, stages_requested, started_at "
                "FROM pipeline_runs WHERE status = 'running' "
                "ORDER BY started_at ASC"
            ).fetchall()

        stuck_runs: list[dict] = []
        for row in rows:
            params = row["params"]
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = None
            stuck_runs.append(
                {
                    "run_id": row["run_id"],
                    "params": params,
                    "stages_requested": row["stages_requested"],
                    "started_at": row["started_at"],
                }
            )
        return stuck_runs

    def build_requeue_plan(
        self,
        run_id: str,
        *,
        strategy: str = "auto",
        stages: int | None = None,
        max_papers: int | None = None,
        max_formulas: int | None = None,
        force: bool | None = None,
    ) -> dict:
        """Build a safe requeue plan for a historical run."""
        source = self.get_run_status(run_id)
        if source is None:
            raise RequeueError(
                f"Run {run_id} not found",
                code="NOT_FOUND",
                status=404,
            )

        source_status = source.get("status")
        if source_status == "running":
            raise RequeueError(
                f"Run {run_id} is still running and cannot be requeued",
                code="RUN_STILL_RUNNING",
                status=409,
            )
        if source_status == "completed":
            raise RequeueError(
                f"Run {run_id} already completed successfully",
                code="RUN_ALREADY_COMPLETED",
                status=409,
            )
        if source_status not in {"partial", "failed"}:
            raise RequeueError(
                f"Run {run_id} with status {source_status!r} is not requeueable",
                code="RUN_NOT_REQUEUEABLE",
                status=409,
            )

        source_params = source.get("params")
        if not isinstance(source_params, dict):
            raise RequeueError(
                f"Run {run_id} has no valid params to requeue",
                code="RUN_PARAMS_INVALID",
                status=409,
            )

        requested_stages = self._normalize_stage_count(
            stages if stages is not None else source.get("stages_requested")
        )
        chosen_strategy = self._select_requeue_strategy(source_params, strategy)

        requeue_params = {
            "query": source_params.get("query"),
            "topic": source_params.get("topic"),
            "paper_id": source_params.get("paper_id"),
            "max_papers": self._coerce_positive_int(
                max_papers if max_papers is not None else source_params.get(
                    "max_papers"
                ),
                default=10,
            ),
            "max_formulas": self._coerce_positive_int(
                max_formulas if max_formulas is not None else source_params.get(
                    "max_formulas"
                ),
                default=50,
            ),
            "force": (
                force if force is not None
                else bool(source_params.get("force", False))
            ),
            "requeue_of": run_id,
            "requeue_strategy": chosen_strategy,
            "requeue_source_status": source_status,
            "requeue_requested_at": datetime.now(timezone.utc).isoformat(),
            "requeue_source_stages_completed": source.get("stages_completed", 0),
            "requeue_source_stages_requested": source.get("stages_requested", 0),
            "requeue_source_failed_stage": self._detect_failed_stage(source),
        }

        if chosen_strategy == "resume_from_current_stage":
            paper_id = requeue_params.get("paper_id")
            if not isinstance(paper_id, int):
                raise RequeueError(
                    f"Run {run_id} has no paper_id to resume",
                    code="RUN_NOT_PAPER_SCOPED",
                    status=409,
                )
            requeue_params["query"] = None
            stage_list = self._resolve_stages(None, paper_id, requested_stages)
            if not stage_list:
                current_stage = self._get_paper_stage(paper_id)
                raise RequeueError(
                    f"Paper {paper_id} is already at terminal stage {current_stage!r}",
                    code="RUN_ALREADY_AT_TERMINAL_STAGE",
                    status=409,
                )
        elif chosen_strategy == "rerun_query":
            query = requeue_params.get("query")
            if not isinstance(query, str) or not query.strip():
                raise RequeueError(
                    f"Run {run_id} has no original query to rerun",
                    code="RUN_NOT_QUERY_SCOPED",
                    status=409,
                )
            query = query.strip()
            requeue_params["query"] = query
            requeue_params["paper_id"] = None
            stage_list = self._resolve_stages(query, None, requested_stages)
        else:
            raise RequeueError(
                f"Unsupported requeue strategy: {chosen_strategy}",
                code="UNSUPPORTED_REQUEUE_STRATEGY",
                status=400,
            )

        return {
            "source_run_id": run_id,
            "source_status": source_status,
            "source_params": source_params,
            "new_run_id": self._generate_run_id(),
            "strategy": chosen_strategy,
            "stages": len(stage_list),
            "stage_names": [stage_name for stage_name, _ in stage_list],
            "params": requeue_params,
        }

    @staticmethod
    def _normalize_stage_count(value: object) -> int:
        """Clamp a user/database stage count into the supported 1-5 range."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 5
        return max(1, min(parsed, 5))

    @staticmethod
    def _coerce_positive_int(value: object, *, default: int) -> int:
        """Coerce an optional numeric field, falling back to a sensible default."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _detect_failed_stage(run_record: dict) -> str | None:
        """Infer the first failed or skipped stage from a stored run result."""
        results = run_record.get("results")
        if isinstance(results, dict):
            for stage_name, _ in STAGE_ORDER:
                stage_result = results.get(stage_name)
                if not isinstance(stage_result, dict):
                    continue
                if stage_result.get("status") in {"failed", "skipped"}:
                    return stage_name
                if stage_result.get("success") is False:
                    return stage_name
                if isinstance(stage_result.get("error"), str):
                    return stage_name

        errors = run_record.get("errors")
        valid_stage_names = {name for name, _ in STAGE_ORDER}
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, str):
                    continue
                stage_name, _, _ = error.partition(":")
                if stage_name in valid_stage_names:
                    return stage_name
        return None

    @staticmethod
    def _select_requeue_strategy(source_params: dict, strategy: str) -> str:
        """Resolve the requested requeue strategy against source run scope."""
        normalized = (strategy or "auto").strip().lower()
        has_paper_id = isinstance(source_params.get("paper_id"), int)
        has_query = isinstance(source_params.get("query"), str) and bool(
            source_params.get("query", "").strip()
        )

        if normalized == "auto":
            if has_paper_id:
                return "resume_from_current_stage"
            if has_query:
                return "rerun_query"
            raise RequeueError(
                "Only paper-scoped or query-scoped runs can be requeued safely",
                code="RUN_SCOPE_UNSUPPORTED",
                status=409,
            )

        if normalized == "resume_from_current_stage":
            if not has_paper_id:
                raise RequeueError(
                    "resume_from_current_stage requires a paper-scoped run",
                    code="RUN_NOT_PAPER_SCOPED",
                    status=409,
                )
            return normalized

        if normalized == "rerun_query":
            if not has_query:
                raise RequeueError(
                    "rerun_query requires a query-scoped run",
                    code="RUN_NOT_QUERY_SCOPED",
                    status=409,
                )
            return normalized

        raise RequeueError(
            f"Unsupported requeue strategy: {strategy}",
            code="UNSUPPORTED_REQUEUE_STRATEGY",
            status=400,
        )

    def fail_runs(self, run_ids: list[str], reason: str) -> int:
        """Mark specific running runs as failed.

        Returns:
            Number of rows updated.
        """
        if not run_ids:
            return 0

        placeholders = ",".join("?" for _ in run_ids)
        error_json = json.dumps([reason])

        with transaction(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE pipeline_runs SET status = 'failed', "
                "errors = ?, completed_at = datetime('now') "
                f"WHERE status = 'running' AND run_id IN ({placeholders})",
                (error_json, *run_ids),
            )
            updated = cursor.rowcount

        for rid in run_ids:
            logger.warning("Marked orphaned pipeline run as failed: %s", rid)
        return updated

    # -- Run persistence --

    def _create_run_record(
        self, run_id: str, params: dict, stages_requested: int
    ) -> None:
        """Insert a new pipeline_runs row with status='running'."""
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs "
                "(run_id, status, params, stages_requested) "
                "VALUES (?, 'running', ?, ?)",
                (run_id, json.dumps(params, default=str), stages_requested),
            )

    def _update_run_record(self, run_id: str, result: dict) -> None:
        """Update pipeline_runs row with final results."""
        with transaction(self.db_path) as conn:
            conn.execute(
                "UPDATE pipeline_runs SET "
                "status = ?, results = ?, errors = ?, "
                "stages_completed = ?, completed_at = datetime('now') "
                "WHERE run_id = ?",
                (
                    result["status"],
                    json.dumps(result.get("results", {}), default=str),
                    json.dumps(result.get("errors", []), default=str),
                    result.get("stages_completed", 0),
                    run_id,
                ),
            )

    def get_run_status(self, run_id: str) -> dict | None:
        """Get a single pipeline run by ID."""
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        # Parse JSON fields
        for field in ("params", "results", "errors"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    def list_runs(self, limit: int = 20) -> list[dict]:
        """List recent pipeline runs."""
        with transaction(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for field in ("params", "results", "errors"):
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results


class ServiceError(Exception):
    """Raised when a service call fails after retries."""
