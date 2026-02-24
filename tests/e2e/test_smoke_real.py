"""End-to-end smoke test against live services.

Runs the full pipeline (discovery -> codegen) on a single arXiv paper
and asserts each stage advanced correctly.  Requires all 5 services to
be running on their default ports (8770-8774).

Usage:
    pytest tests/e2e/test_smoke_real.py -m e2e -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project root is importable so we can reach scripts.smoke_test
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.smoke_test import SmokeReport, check_all_services, run_smoke_test  # noqa: E402

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def smoke_report() -> SmokeReport:
    """Run the full smoke test once and share the report across all tests."""
    health = check_all_services()
    unreachable = [s for s, ok in health.items() if not ok]
    if unreachable:
        pytest.skip(f"Services not running: {', '.join(unreachable)}")

    return run_smoke_test()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_services_healthy():
    """All 5 pipeline services respond to /health."""
    health = check_all_services()
    for svc, ok in health.items():
        assert ok, f"{svc} health check failed"


def test_final_stage_is_codegen(smoke_report: SmokeReport):
    """Pipeline reaches the final 'codegen' stage."""
    assert smoke_report.final_stage == "codegen", (
        f"Expected final stage 'codegen', got '{smoke_report.final_stage}'"
    )


def test_all_steps_succeeded(smoke_report: SmokeReport):
    """Every pipeline step completed without errors."""
    for step in smoke_report.steps:
        assert step.success, (
            f"Step '{step.service}' failed: {step.error}"
        )


def test_formulas_extracted(smoke_report: SmokeReport):
    """Extractor produced at least one formula."""
    assert smoke_report.formulas_extracted > 0, "No formulas extracted"


def test_formulas_validated(smoke_report: SmokeReport):
    """Validator processed at least one formula."""
    assert smoke_report.formulas_validated > 0, "No formulas validated"


def test_code_generated(smoke_report: SmokeReport):
    """Codegen produced code for at least one formula."""
    assert smoke_report.codegen_count > 0, "No code generated"


def test_timing_reasonable(smoke_report: SmokeReport):
    """Total pipeline time stays under 30 minutes."""
    assert smoke_report.total_elapsed_s < 1800, (
        f"Pipeline took {smoke_report.total_elapsed_s:.0f}s (>30 min)"
    )
