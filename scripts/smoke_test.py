#!/usr/bin/env python3
"""Smoke test: run the full pipeline on a single arXiv paper.

Calls the 5 pipeline services in sequence (discovery -> analyzer ->
extractor -> validator -> codegen) and verifies stage progression in
the database.  Uses only stdlib so it can run without installing
project dependencies.

Two modes:
  - Direct (default): calls each service's /process endpoint sequentially.
  - Orchestrator (--via-orchestrator): sends a single POST /run to the
    orchestrator, which handles sequencing, retry, and batch iteration.

Exit code 0 if final stage reaches 'codegen', 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ARXIV_ID = "2003.02743"  # "Generalized Kelly Betting Formula" (~5pp, 185KB)
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "research.db"

SERVICE_PORTS: dict[str, int] = {
    "discovery": 8770,
    "analyzer": 8771,
    "extractor": 8772,
    "validator": 8773,
    "codegen": 8774,
}

# Per-service timeout in seconds
SERVICE_TIMEOUTS: dict[str, int] = {
    "discovery": 60,
    "analyzer": 120,
    "extractor": 3600,  # MinerU ~10min/page on CPU; cached reruns are fast
    "validator": 1800,  # CAS validation ~17s/formula, 50/batch → ~15min
    "codegen": 5400,   # LLM codegen ~90s/formula under load, 50/batch → ~75min
}

ORCHESTRATOR_PORT = 8775

HOST = "localhost"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    service: str
    success: bool
    stage_before: str | None
    stage_after: str | None
    response: dict | None = None
    elapsed_s: float = 0.0
    error: str | None = None


@dataclass
class SmokeReport:
    arxiv_id: str
    paper_id: int | None = None
    final_stage: str | None = None
    steps: list[StepResult] = field(default_factory=list)
    formulas_extracted: int = 0
    formulas_validated: int = 0
    formulas_valid: int = 0
    codegen_count: int = 0
    parse_failure_rate: float = 0.0
    passed: bool = False
    total_elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _url(service: str, path: str = "/process") -> str:
    return f"http://{HOST}:{SERVICE_PORTS[service]}{path}"


def _post(url: str, data: dict, timeout: int) -> dict:
    """POST JSON and return parsed response body."""
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get_paper(db_path: Path, arxiv_id: str) -> tuple[int | None, str | None]:
    """Return (paper_id, stage) or (None, None)."""
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT id, stage FROM papers WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        con.close()


def _reset_paper(db_path: Path, paper_id: int) -> None:
    """Reset a rejected/failed paper to 'discovered' for re-processing."""
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "UPDATE papers SET stage = 'discovered', score = NULL, error = NULL "
            "WHERE id = ?",
            (paper_id,),
        )
        con.commit()
    finally:
        con.close()


def _formula_counts(db_path: Path, paper_id: int) -> dict[str, int]:
    """Return formula statistics for a paper."""
    con = sqlite3.connect(str(db_path))
    try:
        total = con.execute(
            "SELECT COUNT(*) FROM formulas WHERE paper_id = ?", (paper_id,)
        ).fetchone()[0]

        validated = con.execute(
            "SELECT COUNT(*) FROM formulas WHERE paper_id = ? AND stage IN ('validated', 'codegen')",
            (paper_id,),
        ).fetchone()[0]

        valid = con.execute(
            "SELECT COUNT(DISTINCT f.id) FROM formulas f "
            "JOIN validations v ON v.formula_id = f.id "
            "WHERE f.paper_id = ? AND v.is_valid = 1",
            (paper_id,),
        ).fetchone()[0]

        codegen = con.execute(
            "SELECT COUNT(DISTINCT formula_id) FROM generated_code WHERE formula_id IN "
            "(SELECT id FROM formulas WHERE paper_id = ?)",
            (paper_id,),
        ).fetchone()[0]

        unparseable = con.execute(
            "SELECT COUNT(*) FROM formulas WHERE paper_id = ? AND stage = 'failed'",
            (paper_id,),
        ).fetchone()[0]

        return {
            "extracted": total,
            "validated": validated,
            "valid": valid,
            "codegen": codegen,
            "unparseable": unparseable,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def check_all_services() -> dict[str, bool]:
    """Ping /health on every service, return {name: reachable}."""
    results: dict[str, bool] = {}
    for name, port in SERVICE_PORTS.items():
        try:
            resp = _get(f"http://{HOST}:{port}/health", timeout=5)
            results[name] = resp.get("status") == "ok"
        except Exception:
            results[name] = False
    return results


# ---------------------------------------------------------------------------
# Core pipeline runner
# ---------------------------------------------------------------------------


def run_smoke_test(
    arxiv_id: str = DEFAULT_ARXIV_ID,
    db_path: Path = DEFAULT_DB_PATH,
    max_formulas: int = 50,
) -> SmokeReport:
    """Execute the full 5-stage pipeline on *arxiv_id* and return a report."""
    report = SmokeReport(arxiv_id=arxiv_id)
    t0 = time.monotonic()

    # -- health check ---------------------------------------------------
    health = check_all_services()
    unreachable = [s for s, ok in health.items() if not ok]
    if unreachable:
        report.steps.append(
            StepResult(
                service="health",
                success=False,
                stage_before=None,
                stage_after=None,
                error=f"Services unreachable: {', '.join(unreachable)}",
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report

    # -- Clean stale state -----------------------------------------------
    _existing_id, _existing_stage = _get_paper(db_path, arxiv_id)
    if _existing_stage in ("rejected", "failed"):
        _reset_paper(db_path, _existing_id)

    # -- Step 1: discovery ----------------------------------------------
    stage_before = _get_paper(db_path, arxiv_id)[1]  # may be None
    step = _run_step(
        "discovery",
        {"query": f"id:{arxiv_id}", "max_results": 1},
        db_path,
        arxiv_id,
        stage_before,
    )
    report.steps.append(step)
    if not step.success:
        report.total_elapsed_s = time.monotonic() - t0
        return report

    # Retrieve paper_id after discovery
    paper_id, current_stage = _get_paper(db_path, arxiv_id)
    if paper_id is None:
        report.steps.append(
            StepResult(
                service="discovery",
                success=False,
                stage_before=stage_before,
                stage_after=None,
                error="Paper not found in DB after discovery",
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report

    report.paper_id = paper_id

    # -- Steps 2-5: analyzer, extractor, validator, codegen -------------
    remaining = ["analyzer", "extractor", "validator", "codegen"]
    for svc in remaining:
        _, stage_before = _get_paper(db_path, arxiv_id)

        # Stop if paper was rejected or failed by a previous stage
        if stage_before in ("rejected", "failed"):
            break

        if svc in ("validator", "codegen"):
            # Batch loop: call until formulas_processed == 0, like the orchestrator
            batch = 0
            while batch < 100:  # safety cap
                payload: dict = {"paper_id": paper_id, "max_formulas": max_formulas}
                step = _run_step(svc, payload, db_path, arxiv_id, stage_before)
                report.steps.append(step)
                if not step.success:
                    break
                processed = (step.response or {}).get("formulas_processed", 0)
                batch += 1
                if processed == 0:
                    break
            if not step.success:
                break
        else:
            payload = {"paper_id": paper_id, "max_papers": 1}
            step = _run_step(svc, payload, db_path, arxiv_id, stage_before)
            report.steps.append(step)
            if not step.success:
                break

    # -- Collect final stats --------------------------------------------
    paper_id_final, final_stage = _get_paper(db_path, arxiv_id)
    report.paper_id = paper_id_final
    report.final_stage = final_stage

    if paper_id_final is not None:
        counts = _formula_counts(db_path, paper_id_final)
        report.formulas_extracted = counts["extracted"]
        report.formulas_validated = counts["validated"]
        report.formulas_valid = counts["valid"]
        report.codegen_count = counts["codegen"]
        if counts["extracted"] > 0:
            report.parse_failure_rate = counts["unparseable"] / counts["extracted"]

    report.passed = final_stage == "codegen"
    report.total_elapsed_s = time.monotonic() - t0
    return report


def _run_step(
    service: str,
    payload: dict,
    db_path: Path,
    arxiv_id: str,
    stage_before: str | None,
) -> StepResult:
    """Call one service's /process endpoint and return a StepResult."""
    t0 = time.monotonic()
    try:
        resp = _post(
            _url(service),
            payload,
            timeout=SERVICE_TIMEOUTS[service],
        )
        elapsed = time.monotonic() - t0
        _, stage_after = _get_paper(db_path, arxiv_id)

        # Check for errors in the response
        errors = resp.get("errors", [])
        error_msg = "; ".join(errors) if errors else None

        return StepResult(
            service=service,
            success=True,
            stage_before=stage_before,
            stage_after=stage_after,
            response=resp,
            elapsed_s=elapsed,
            error=error_msg,
        )
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - t0
        try:
            body = exc.read().decode()
        except Exception:
            body = str(exc)
        return StepResult(
            service=service,
            success=False,
            stage_before=stage_before,
            stage_after=None,
            elapsed_s=elapsed,
            error=f"HTTP {exc.code}: {body}",
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return StepResult(
            service=service,
            success=False,
            stage_before=stage_before,
            stage_after=None,
            elapsed_s=elapsed,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Orchestrator mode
# ---------------------------------------------------------------------------


def _orchestrator_url(path: str = "/run") -> str:
    return f"http://{HOST}:{ORCHESTRATOR_PORT}{path}"


def run_smoke_test_via_orchestrator(
    arxiv_id: str = DEFAULT_ARXIV_ID,
    db_path: Path = DEFAULT_DB_PATH,
    max_formulas: int = 50,
    timeout: int = 0,
) -> SmokeReport:
    """Execute the pipeline via orchestrator /run endpoint.

    Instead of calling each service directly, sends a single POST /run
    to the orchestrator and lets it handle sequencing, retry, and batching.
    """
    report = SmokeReport(arxiv_id=arxiv_id)
    t0 = time.monotonic()

    # If no timeout specified, use sum of per-service timeouts + buffer
    if timeout <= 0:
        timeout = sum(SERVICE_TIMEOUTS.values()) + 300

    # -- Health check: orchestrator + downstream services ------------------
    try:
        orch_health = _get(_orchestrator_url("/health"), timeout=10)
        if orch_health.get("status") != "ok":
            report.steps.append(
                StepResult(
                    service="orchestrator",
                    success=False,
                    stage_before=None,
                    stage_after=None,
                    error="Orchestrator health check failed",
                )
            )
            report.total_elapsed_s = time.monotonic() - t0
            return report
    except Exception as exc:
        report.steps.append(
            StepResult(
                service="orchestrator",
                success=False,
                stage_before=None,
                stage_after=None,
                error=f"Orchestrator unreachable: {exc}",
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report

    try:
        svc_status = _get(_orchestrator_url("/status/services"), timeout=30)
        if not svc_status.get("all_healthy"):
            down = [
                name
                for name, info in svc_status.get("services", {}).items()
                if info.get("status") != "ok"
            ]
            report.steps.append(
                StepResult(
                    service="health",
                    success=False,
                    stage_before=None,
                    stage_after=None,
                    error=f"Downstream services unhealthy: {', '.join(down)}",
                )
            )
            report.total_elapsed_s = time.monotonic() - t0
            return report
    except Exception as exc:
        report.steps.append(
            StepResult(
                service="health",
                success=False,
                stage_before=None,
                stage_after=None,
                error=f"Service status check failed: {exc}",
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report

    # -- Clean stale state -------------------------------------------------
    _existing_id, _existing_stage = _get_paper(db_path, arxiv_id)
    if _existing_stage in ("rejected", "failed"):
        _reset_paper(db_path, _existing_id)

    paper_id_for_run, stage_before = _get_paper(db_path, arxiv_id)

    # -- POST /run to orchestrator -----------------------------------------
    # Include paper_id so stages after discovery target this specific paper
    # instead of running in untargeted batch mode.
    run_payload = {
        "query": f"id:{arxiv_id}",
        "stages": 5,
        "max_papers": 1,
        "max_formulas": max_formulas,
    }
    if paper_id_for_run is not None:
        run_payload["paper_id"] = paper_id_for_run

    step_t0 = time.monotonic()
    try:
        result = _post(_orchestrator_url("/run"), run_payload, timeout=timeout)
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - step_t0
        try:
            body = exc.read().decode()
        except Exception:
            body = str(exc)
        report.steps.append(
            StepResult(
                service="orchestrator",
                success=False,
                stage_before=stage_before,
                stage_after=None,
                elapsed_s=elapsed,
                error=f"HTTP {exc.code}: {body}",
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report
    except Exception as exc:
        elapsed = time.monotonic() - step_t0
        report.steps.append(
            StepResult(
                service="orchestrator",
                success=False,
                stage_before=stage_before,
                stage_after=None,
                elapsed_s=elapsed,
                error=str(exc),
            )
        )
        report.total_elapsed_s = time.monotonic() - t0
        return report

    run_elapsed = time.monotonic() - step_t0

    # -- Map orchestrator response to StepResults --------------------------
    stage_results = result.get("results", {})
    for stage_name in ("discovery", "analyzer", "extractor", "validator", "codegen"):
        if stage_name not in stage_results:
            continue
        sr = stage_results[stage_name]
        errors = sr.get("errors", [])
        report.steps.append(
            StepResult(
                service=stage_name,
                success="error" not in sr,
                stage_before=None,
                stage_after=None,
                response=sr,
                elapsed_s=sr.get("time_ms", 0) / 1000.0,
                error=sr.get("error") or ("; ".join(errors) if errors else None),
            )
        )

    # Add overall orchestrator step
    report.steps.append(
        StepResult(
            service="orchestrator",
            success=result.get("status") == "completed",
            stage_before=stage_before,
            stage_after=None,
            response=result,
            elapsed_s=run_elapsed,
            error="; ".join(result.get("errors", [])) or None,
        )
    )

    # -- Verify DB state and collect stats ---------------------------------
    paper_id, final_stage = _get_paper(db_path, arxiv_id)
    report.paper_id = paper_id
    report.final_stage = final_stage

    if paper_id is not None:
        counts = _formula_counts(db_path, paper_id)
        report.formulas_extracted = counts["extracted"]
        report.formulas_validated = counts["validated"]
        report.formulas_valid = counts["valid"]
        report.codegen_count = counts["codegen"]
        if counts["extracted"] > 0:
            report.parse_failure_rate = counts["unparseable"] / counts["extracted"]

    report.passed = final_stage == "codegen"
    report.total_elapsed_s = time.monotonic() - t0
    return report


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def print_report(report: SmokeReport) -> None:
    sep = "=" * 60

    print(f"\n{sep}")
    print(f"  SMOKE TEST REPORT: {report.arxiv_id}")
    print(sep)
    print(f"  Paper ID:     {report.paper_id or 'N/A'}")
    print(f"  Final Stage:  {report.final_stage or 'N/A'}")

    tag = "PASS" if report.passed else "FAIL"
    print(f"  Result:       {tag}")
    print(f"  Total Time:   {report.total_elapsed_s:.1f}s")

    print(f"\n  {'--- Stage Progression ---':^50}")
    for step in report.steps:
        mark = "OK  " if step.success else "FAIL"
        before = step.stage_before or "not_found"
        after = step.stage_after or "?"
        line = f"  [{mark}] {step.service:<14} {before:<14} -> {after:<14} ({step.elapsed_s:.1f}s)"
        print(line)
        if step.error:
            print(f"         {step.error}")

    print(f"\n  {'--- Pipeline Stats ---':^50}")
    print(f"  Formulas extracted:     {report.formulas_extracted}")
    print(f"  Formulas validated:     {report.formulas_validated}")
    print(f"  Formulas valid (CAS):   {report.formulas_valid}")
    print(f"  Code generated:         {report.codegen_count}")
    if report.formulas_extracted > 0:
        print(f"  Parse failure rate:     {report.parse_failure_rate:.1%}")
    print(sep)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full research pipeline on a single arXiv paper.",
    )
    parser.add_argument(
        "arxiv_id",
        nargs="?",
        default=DEFAULT_ARXIV_ID,
        help=f"arXiv paper ID (default: {DEFAULT_ARXIV_ID})",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Service host (default: localhost)",
    )
    parser.add_argument(
        "--max-formulas",
        type=int,
        default=50,
        help="Max formulas per validator/codegen batch (default: 50)",
    )
    parser.add_argument(
        "--via-orchestrator",
        action="store_true",
        help="Route pipeline through orchestrator /run instead of direct service calls",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="HTTP timeout in seconds for orchestrator mode (default: auto)",
    )
    args = parser.parse_args(argv)

    global HOST
    HOST = args.host

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        return 1

    if args.via_orchestrator:
        report = run_smoke_test_via_orchestrator(
            args.arxiv_id, db_path, args.max_formulas, args.timeout
        )
    else:
        report = run_smoke_test(args.arxiv_id, db_path, args.max_formulas)
    print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
