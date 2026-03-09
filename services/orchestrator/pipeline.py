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

def _stage_port(service: str, default: int) -> int:
    raw = os.environ.get(f"RP_{service.upper()}_PORT", str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


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
    ("cas", os.environ.get("RP_VALIDATOR_CAS_URL", "http://localhost:8769"), "/health"),
    ("rag", os.environ.get("RP_EXTRACTOR_RAG_URL", "http://localhost:8767"), "/health"),
    ("ollama", os.environ.get("RP_CODEGEN_OLLAMA_URL", "http://localhost:11434"), "/"),
]

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
    "analyzer": {"paper_id": "paper_id", "max_papers": "max_papers", "force": "force"},
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

    # Per-stage timeout overrides (seconds).  Codegen processes N formulas
    # sequentially (SymPy parse + codegen + optional LLM fallback per formula),
    # so it needs a much longer timeout than fast stages like discovery.
    STAGE_TIMEOUTS: dict[str, int] = {
        "codegen": int(os.environ.get("RP_ORCHESTRATOR_CODEGEN_TIMEOUT", "900")),
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.timeout = int(os.environ.get("RP_ORCHESTRATOR_TIMEOUT", "300"))
        self.retry_max = int(os.environ.get("RP_ORCHESTRATOR_RETRY_MAX", "3"))
        self.retry_backoff = float(
            os.environ.get("RP_ORCHESTRATOR_RETRY_BACKOFF", "4.0")
        )

    def run(
        self,
        query: str | None = None,
        paper_id: int | None = None,
        stages: int = 5,
        max_papers: int = 10,
        max_formulas: int = 50,
        force: bool = False,
        run_id: str | None = None,
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
            "paper_id": paper_id,
            "max_papers": max_papers,
            "max_formulas": max_formulas,
            "force": force,
        }

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
        has_failure = False

        # Stages that process formulas in batches need iteration
        BATCH_STAGES = {"validator", "codegen"}
        MAX_BATCH_ITERATIONS = 100

        try:
            for stage_name, port in stage_list:
                stage_params = self._build_stage_params(stage_name, params)

                if not stage_params:
                    # Skip stages with no applicable params (e.g., Discovery without query)
                    logger.info("Skipping %s: no applicable params", stage_name)
                    STAGE_COMPLETED.labels(stage=stage_name, result="skipped").inc()
                    continue

                logger.info("Dispatching stage: %s (port %d)", stage_name, port)
                stage_start = time.time()

                stage_timeout = self.STAGE_TIMEOUTS.get(stage_name, self.timeout)
                try:
                    if stage_name in BATCH_STAGES:
                        # Iterate until all formulas are processed
                        batch_results: list[dict] = []
                        for iteration in range(1, MAX_BATCH_ITERATIONS + 1):
                            result = self._call_service_with_retry(
                                f"http://localhost:{port}/process", stage_params,
                                timeout=stage_timeout,
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
                            f"http://localhost:{port}/process", stage_params,
                            timeout=stage_timeout,
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
                    results[stage_name] = {"error": str(e), "time_ms": stage_ms}
                    has_failure = True
                    STAGE_DURATION.labels(stage=stage_name).observe(stage_duration)
                    STAGE_COMPLETED.labels(stage=stage_name, result="failure").inc()
                    logger.error("Stage %s failed: %s", stage_name, e)
                    # Continue to next stage — other papers may be processable

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

        return result

    def _call_service_with_retry(
        self, url: str, params: dict, *, timeout: int | None = None,
    ) -> dict:
        """Call a service endpoint with exponential backoff retry.

        Args:
            url: Service /process URL.
            params: Request body.
            timeout: Request timeout in seconds (overrides default).

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
            try:
                resp = requests.get(
                    f"http://localhost:{port}/health", timeout=5
                )
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
                healthy = resp.status_code < 400
            except requests.RequestException:
                healthy = False

            deps[name] = {"url": base_url, "healthy": healthy}
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
