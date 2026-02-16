"""Pipeline execution engine — stage dispatch, retry, and status tracking.

Coordinates the 5 downstream services (Discovery → Analyzer → Extractor →
Validator → Codegen) via HTTP calls to their /process endpoints.

Environment:
    RP_ORCHESTRATOR_RETRY_MAX=3             # Max retries per service call
    RP_ORCHESTRATOR_RETRY_BACKOFF=4.0       # Backoff base (seconds)
    RP_ORCHESTRATOR_TIMEOUT=300             # Request timeout (seconds)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from shared.db import transaction

logger = logging.getLogger(__name__)

# Stage order: (name, port)
STAGE_ORDER: list[tuple[str, int]] = [
    ("discovery", 8770),
    ("analyzer", 8771),
    ("extractor", 8772),
    ("validator", 8773),
    ("codegen", 8774),
]

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
    ) -> dict:
        """Execute a pipeline run.

        Args:
            query: arXiv search query (triggers Discovery).
            paper_id: Advance specific paper.
            stages: How many stages to advance (1-5).
            max_papers: Max papers per batch.
            max_formulas: Max formulas per batch.
            force: Reprocess already-processed items.

        Returns:
            Run result dict with run_id, status, results, errors.
        """
        run_id = self._generate_run_id()
        start = time.time()

        params = {
            "query": query,
            "paper_id": paper_id,
            "max_papers": max_papers,
            "max_formulas": max_formulas,
            "force": force,
        }

        # Determine which stages to run
        stage_list = self._resolve_stages(query, paper_id, stages)

        results: dict[str, dict] = {}
        errors: list[str] = []
        stages_completed = 0
        has_failure = False

        # Stages that process formulas in batches need iteration
        BATCH_STAGES = {"validator", "codegen"}
        MAX_BATCH_ITERATIONS = 100

        for stage_name, port in stage_list:
            stage_params = self._build_stage_params(stage_name, params)

            if not stage_params:
                # Skip stages with no applicable params (e.g., Discovery without query)
                logger.info("Skipping %s: no applicable params", stage_name)
                continue

            logger.info("Dispatching stage: %s (port %d)", stage_name, port)
            stage_start = time.time()

            try:
                if stage_name in BATCH_STAGES:
                    # Iterate until all formulas are processed
                    batch_results: list[dict] = []
                    for iteration in range(1, MAX_BATCH_ITERATIONS + 1):
                        result = self._call_service_with_retry(
                            f"http://localhost:{port}/process", stage_params
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
                        f"http://localhost:{port}/process", stage_params
                    )

                stage_ms = int((time.time() - stage_start) * 1000)
                result["time_ms"] = stage_ms
                results[stage_name] = result
                stages_completed += 1
                logger.info(
                    "Stage %s completed in %dms", stage_name, stage_ms
                )
            except ServiceError as e:
                stage_ms = int((time.time() - stage_start) * 1000)
                error_msg = f"{stage_name}: {e}"
                errors.append(error_msg)
                results[stage_name] = {"error": str(e), "time_ms": stage_ms}
                has_failure = True
                logger.error("Stage %s failed: %s", stage_name, e)
                # Continue to next stage — other papers may be processable

        elapsed_ms = int((time.time() - start) * 1000)

        status = "completed"
        if has_failure:
            status = "partial" if stages_completed > 0 else "failed"

        return {
            "run_id": run_id,
            "status": status,
            "stages_completed": stages_completed,
            "stages_requested": len(stage_list),
            "results": results,
            "errors": errors,
            "time_ms": elapsed_ms,
        }

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

    def _call_service_with_retry(self, url: str, params: dict) -> dict:
        """Call a service endpoint with exponential backoff retry.

        Args:
            url: Service /process URL.
            params: Request body.

        Returns:
            Parsed JSON response.

        Raises:
            ServiceError: If all retries exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(self.retry_max + 1):
            try:
                resp = requests.post(
                    url, json=params, timeout=self.timeout
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
                last_error = ServiceError(f"Timeout after {self.timeout}s: {e}")

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

        return {"all_healthy": all_healthy, "services": services}

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a unique run ID.

        Format: run-YYYYMMDD-HHMMSS-XXXXXX
        """
        now = datetime.now(timezone.utc)
        short_id = uuid.uuid4().hex[:6]
        return f"run-{now.strftime('%Y%m%d-%H%M%S')}-{short_id}"


class ServiceError(Exception):
    """Raised when a service call fails after retries."""
