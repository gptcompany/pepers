"""Integration tests: Phase 28-29 regression — stage transitions, batch overflow, filtering.

Verifies:
- Validator/Codegen update papers.stage correctly (Phase 28 fix)
- Orchestrator batch iteration loop handles >50 formulas (Phase 28 fix)
- Safety cap stops infinite batch loops (Phase 28 fix)
- Trivial formulas are filtered before reaching batch queue (Phase 29 fix)
- clean_latex enables codegen on previously-failing formulas (Phase 29 fix)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from shared.db import transaction
from services.orchestrator.pipeline import PipelineRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_paper_stage(db_path: str, paper_id: int) -> str:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT stage FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    return row["stage"] if row else "unknown"


def _get_formula_stages(db_path: str, paper_id: int) -> list[str]:
    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT stage FROM formulas WHERE paper_id = ? ORDER BY id",
            (paper_id,),
        ).fetchall()
    return [r["stage"] for r in rows]


def _count_formulas_by_stage(db_path: str, stage: str) -> int:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM formulas WHERE stage = ?", (stage,)
        ).fetchone()
    return row["cnt"]


# ---------------------------------------------------------------------------
# Stage Transitions (Phase 28 regression)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStageTransitions:
    """Verify paper.stage advances correctly after validator/codegen."""

    def test_validator_updates_paper_stage(self, extracted_formula_db):
        """Paper at 'extracted' → validator processes → paper.stage = 'validated'."""
        db_path = str(extracted_formula_db)

        # Pre-condition
        assert _get_paper_stage(db_path, 1) == "extracted"

        # Mock CAS client to return valid result
        mock_cas_response = MagicMock()
        mock_result = MagicMock()
        mock_result.engine = "sympy"
        mock_result.success = True
        mock_result.is_valid = True
        mock_result.simplified = "p/a - q/b"
        mock_result.error = None
        mock_result.time_ms = 50
        mock_cas_response.results = [mock_result]

        mock_consensus = MagicMock()
        mock_consensus.outcome.value = "valid"
        mock_consensus.detail = "Sympy confirms"

        with (
            patch("services.validator.main.CASClient") as mock_cls,
            patch("services.validator.main.apply_consensus", return_value=mock_consensus),
        ):
            mock_client = MagicMock()
            mock_client.health.return_value = True
            mock_client.validate.return_value = mock_cas_response
            mock_cls.return_value = mock_client

            from services.validator.main import ValidatorHandler
            handler = ValidatorHandler.__new__(ValidatorHandler)
            handler.db_path = db_path
            handler.cas_url = "http://localhost:8769"
            handler.cas_timeout = 120
            handler.max_formulas_default = 50
            handler.engines = ["sympy"]

            result = handler.handle_process({})

        assert result is not None
        assert result["formulas_processed"] >= 1
        assert _get_paper_stage(db_path, 1) == "validated"

    def test_codegen_updates_paper_stage(self, validated_formula_db):
        """Paper at 'validated' → codegen processes → paper.stage = 'codegen'."""
        db_path = str(validated_formula_db)

        # Pre-condition
        assert _get_paper_stage(db_path, 1) == "validated"

        mock_code_results = [
            {"language": "c99", "code": "double f(double p, double a) { return p/a; }",
             "metadata": {"variables": ["p", "a"]}, "error": None},
            {"language": "rust", "code": "", "metadata": None,
             "error": "parse error"},
            {"language": "python", "code": "def f(p, a): return p/a",
             "metadata": {"variables": ["p", "a"]}, "error": None},
        ]

        with (
            patch("services.codegen.main.explain_formulas_batch", return_value={}),
            patch("services.codegen.main.generate_all", return_value=mock_code_results),
        ):
            from services.codegen.main import CodegenHandler
            handler = CodegenHandler.__new__(CodegenHandler)
            handler.db_path = db_path
            handler.max_formulas_default = 50

            result = handler.handle_process({})

        assert result is not None
        assert result["formulas_processed"] >= 1
        assert _get_paper_stage(db_path, 1) == "codegen"

    def test_validator_no_update_on_all_failed(self, extracted_formula_db):
        """All formulas fail → paper.stage stays 'extracted'."""
        db_path = str(extracted_formula_db)

        with (
            patch("services.validator.main.CASClient") as mock_cls,
        ):
            mock_client = MagicMock()
            mock_client.health.return_value = True
            mock_client.validate.side_effect = Exception("CAS crash")
            mock_cls.return_value = mock_client

            from services.validator.main import ValidatorHandler
            handler = ValidatorHandler.__new__(ValidatorHandler)
            handler.db_path = db_path
            handler.cas_url = "http://localhost:8769"
            handler.cas_timeout = 120
            handler.max_formulas_default = 50
            handler.engines = ["sympy"]

            # Need to mock send_error_json since CAS error is caught internally
            handler.handle_process({})

        # Paper stage must NOT advance
        assert _get_paper_stage(db_path, 1) == "extracted"

    def test_codegen_no_update_on_all_failed(self, validated_formula_db):
        """All formulas fail codegen → paper.stage stays 'validated'."""
        db_path = str(validated_formula_db)

        mock_code_results = [
            {"language": "c99", "code": "", "metadata": None, "error": "parse fail"},
            {"language": "rust", "code": "", "metadata": None, "error": "parse fail"},
            {"language": "python", "code": "", "metadata": None, "error": "parse fail"},
        ]

        with (
            patch("services.codegen.main.explain_formulas_batch", return_value={}),
            patch("services.codegen.main.generate_all", return_value=mock_code_results),
        ):
            from services.codegen.main import CodegenHandler
            handler = CodegenHandler.__new__(CodegenHandler)
            handler.db_path = db_path
            handler.max_formulas_default = 50

            result = handler.handle_process({})

        assert result is not None
        assert result["formulas_processed"] >= 1
        # Paper stage must NOT advance
        assert _get_paper_stage(db_path, 1) == "validated"

    def test_full_stage_progression(self, extracted_formula_db):
        """Paper goes extracted → validated → codegen with DB check at each step."""
        db_path = str(extracted_formula_db)

        # Step 1: Validate
        mock_cas_response = MagicMock()
        mock_result = MagicMock()
        mock_result.engine = "sympy"
        mock_result.success = True
        mock_result.is_valid = True
        mock_result.simplified = "p/a - q/b"
        mock_result.error = None
        mock_result.time_ms = 50
        mock_cas_response.results = [mock_result]

        mock_consensus = MagicMock()
        mock_consensus.outcome.value = "valid"
        mock_consensus.detail = "ok"

        with (
            patch("services.validator.main.CASClient") as mock_cls,
            patch("services.validator.main.apply_consensus", return_value=mock_consensus),
        ):
            mock_client = MagicMock()
            mock_client.health.return_value = True
            mock_client.validate.return_value = mock_cas_response
            mock_cls.return_value = mock_client

            from services.validator.main import ValidatorHandler
            handler = ValidatorHandler.__new__(ValidatorHandler)
            handler.db_path = db_path
            handler.cas_url = "http://localhost:8769"
            handler.cas_timeout = 120
            handler.max_formulas_default = 50
            handler.engines = ["sympy"]

            handler.handle_process({})

        assert _get_paper_stage(db_path, 1) == "validated"
        assert _get_formula_stages(db_path, 1) == ["validated"]

        # Step 2: Codegen
        mock_code_results = [
            {"language": "c99", "code": "double f(void) { return 1.0; }",
             "metadata": {}, "error": None},
            {"language": "rust", "code": "fn f() -> f64 { 1.0 }",
             "metadata": {}, "error": None},
            {"language": "python", "code": "def f(): return 1.0",
             "metadata": {}, "error": None},
        ]

        with (
            patch("services.codegen.main.explain_formulas_batch", return_value={}),
            patch("services.codegen.main.generate_all", return_value=mock_code_results),
        ):
            from services.codegen.main import CodegenHandler
            handler = CodegenHandler.__new__(CodegenHandler)
            handler.db_path = db_path
            handler.max_formulas_default = 50

            handler.handle_process({})

        assert _get_paper_stage(db_path, 1) == "codegen"
        assert _get_formula_stages(db_path, 1) == ["codegen"]


# ---------------------------------------------------------------------------
# Batch Iteration (Phase 28 regression)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBatchIteration:
    """Verify orchestrator batch loop processes all formulas."""

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_processes_all_formulas(self, mock_post, multi_formula_db):
        """75 formulas: orchestrator calls validator 2x (50+25), all processed."""
        db_path = str(multi_formula_db)

        call_count = 0

        def mock_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            # First call: 50 processed, second: 25, third: 0
            if call_count == 1:
                resp.json.return_value = {
                    "formulas_processed": 50,
                    "formulas_valid": 40,
                    "formulas_invalid": 5,
                    "formulas_failed": 5,
                    "errors": [],
                }
            elif call_count == 2:
                resp.json.return_value = {
                    "formulas_processed": 25,
                    "formulas_valid": 20,
                    "formulas_invalid": 3,
                    "formulas_failed": 2,
                    "errors": [],
                }
            else:
                resp.json.return_value = {
                    "formulas_processed": 0,
                    "formulas_valid": 0,
                    "formulas_invalid": 0,
                    "formulas_failed": 0,
                    "errors": [],
                }
            return resp

        mock_post.side_effect = mock_response

        runner = PipelineRunner(db_path)
        result = runner.run(paper_id=1, stages=1, max_formulas=50)

        # Validator is stage idx 3 for paper at "extracted" (idx 2 + 1)
        assert "validator" in result["results"]
        validator_result = result["results"]["validator"]
        assert validator_result["batch_iterations"] == 3
        assert validator_result["formulas_processed"] == 75
        assert validator_result["formulas_valid"] == 60

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_merge_sums_counters(self, mock_post, multi_formula_db):
        """Merged result has correct totals across iterations."""
        db_path = str(multi_formula_db)

        responses = [
            {"formulas_processed": 30, "formulas_valid": 25,
             "formulas_failed": 5, "errors": ["err1"]},
            {"formulas_processed": 20, "formulas_valid": 18,
             "formulas_failed": 2, "errors": ["err2"]},
            {"formulas_processed": 0, "formulas_valid": 0,
             "formulas_failed": 0, "errors": []},
        ]
        call_idx = 0

        def mock_response(*args, **kwargs):
            nonlocal call_idx
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = responses[min(call_idx, len(responses) - 1)]
            call_idx += 1
            return resp

        mock_post.side_effect = mock_response

        runner = PipelineRunner(db_path)
        result = runner.run(paper_id=1, stages=1, max_formulas=50)

        validator_result = result["results"]["validator"]
        assert validator_result["formulas_processed"] == 50
        assert validator_result["formulas_valid"] == 43
        assert validator_result["formulas_failed"] == 7
        assert validator_result["errors"] == ["err1", "err2"]

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_stops_at_zero(self, mock_post, extracted_formula_db):
        """Loop exits when formulas_processed == 0."""
        db_path = str(extracted_formula_db)

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"formulas_processed": 0, "errors": []}
        mock_post.return_value = resp

        runner = PipelineRunner(db_path)
        runner.run(paper_id=1, stages=1, max_formulas=50)

        # Should call just once and stop
        assert mock_post.call_count == 1

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_safety_cap(self, mock_post, multi_formula_db, caplog):
        """Mock infinite work → loop stops at 100 iterations."""
        db_path = str(multi_formula_db)

        # Always return 1 formula processed (simulates infinite work)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "formulas_processed": 1,
            "formulas_valid": 1,
            "errors": [],
        }
        mock_post.return_value = resp

        runner = PipelineRunner(db_path)

        with caplog.at_level(logging.INFO, logger="services.orchestrator.pipeline"):
            result = runner.run(paper_id=1, stages=1, max_formulas=50)

        # Must stop at 100 iterations (MAX_BATCH_ITERATIONS)
        assert mock_post.call_count == 100
        validator_result = result["results"]["validator"]
        assert validator_result["batch_iterations"] == 100
        assert validator_result["formulas_processed"] == 100

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_partial_failure(self, mock_post, multi_formula_db):
        """First batch OK, second raises ServiceError → results merged, errors captured."""
        db_path = str(multi_formula_db)

        call_count = 0

        def mock_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "formulas_processed": 50,
                    "formulas_valid": 45,
                    "formulas_failed": 5,
                    "errors": [],
                }
                return resp
            else:
                # Second call: server error → triggers retry then ServiceError
                resp = MagicMock()
                resp.status_code = 500
                resp.text = "Internal Server Error"
                return resp

        mock_post.side_effect = mock_response

        runner = PipelineRunner(db_path)
        runner.retry_max = 0  # No retries to speed up test

        result = runner.run(paper_id=1, stages=1, max_formulas=50)

        # Stage should be in results but with error
        assert result["status"] in ("partial", "failed")
        assert len(result["errors"]) > 0

    def test_clean_latex_in_codegen_flow(self, validated_formula_db):
        r"""Formula with \tag{N} → clean_latex strips it → codegen succeeds."""
        db_path = str(validated_formula_db)

        # Replace the formula with one containing \tag
        with transaction(db_path) as conn:
            conn.execute(
                r"UPDATE formulas SET latex = 'x^2 + y^2 = z^2 \tag{13}' WHERE id = 1"
            )

        from services.codegen.generators import clean_latex, parse_formula

        # Verify clean_latex strips \tag
        cleaned = clean_latex(r"x^2 + y^2 = z^2 \tag{13}")
        assert r"\tag" not in cleaned

        # Verify parse_formula succeeds on the cleaned version
        expr = parse_formula(r"x^2 + y^2 = z^2 \tag{13}")
        assert expr is not None


# ---------------------------------------------------------------------------
# Stage Resolution (Phase 28 regression)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestResolveStages:
    """Verify _resolve_stages for edge cases."""

    def test_rejected_paper_returns_empty(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.99999", "Rejected", "rejected"),
            )

        runner = PipelineRunner(db_path)
        stages = runner._resolve_stages(None, 1, 5)
        assert stages == []

    def test_failed_paper_returns_empty(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.99998", "Failed", "failed"),
            )

        runner = PipelineRunner(db_path)
        stages = runner._resolve_stages(None, 1, 5)
        assert stages == []

    def test_paper_at_codegen_returns_empty(self, initialized_db):
        """Paper already at final stage → no more stages to run."""
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.99997", "Done", "codegen"),
            )

        runner = PipelineRunner(db_path)
        stages = runner._resolve_stages(None, 1, 5)
        assert stages == []

    def test_paper_at_extracted_starts_from_validator(self, initialized_db):
        """stage='extracted' → starts at validator (idx 3)."""
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.99996", "Extracted", "extracted"),
            )

        runner = PipelineRunner(db_path)
        stages = runner._resolve_stages(None, 1, 5)
        stage_names = [s[0] for s in stages]
        assert stage_names[0] == "validator"
        assert "codegen" in stage_names


# ---------------------------------------------------------------------------
# Filtered Formulas (Phase 29 regression)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFilteredFormulasNoInfiniteLoop:
    """Verify trivial formulas don't create infinite batch loops."""

    def test_trivial_formulas_filtered_at_extraction(self):
        """Fragments like \\alpha, ^{1} are rejected by filter_formulas."""
        from services.extractor.latex import filter_formulas

        trivial = [
            {"latex": r"\alpha"},
            {"latex": r"^{1}"},
            {"latex": r"\mu"},
            {"latex": r"\sigma_t"},
            {"latex": r"\pi"},
        ]
        result = filter_formulas(trivial)
        assert len(result) == 0

    def test_nontrivial_formulas_pass_filter(self):
        """Real formulas pass through filter_formulas."""
        from services.extractor.latex import filter_formulas

        nontrivial = [
            {"latex": r"f^* = \frac{p}{a} - \frac{q}{b}"},
            {"latex": r"E[r] = \sum_{i=1}^{n} p_i r_i"},
            {"latex": r"\sigma^2 = \frac{1}{n}\sum (x_i - \mu)^2"},
        ]
        result = filter_formulas(nontrivial)
        assert len(result) == 3

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_terminates_with_zero_eligible(
        self, mock_post, initialized_db
    ):
        """Zero eligible formulas → validator returns 0, batch exits immediately."""
        db_path = str(initialized_db)

        # Seed paper but NO formulas in 'extracted' stage
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test", "extracted"),
            )

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"formulas_processed": 0, "errors": []}
        mock_post.return_value = resp

        runner = PipelineRunner(db_path)
        runner.run(paper_id=1, stages=1, max_formulas=50)

        # Validator called once, gets 0, exits
        assert mock_post.call_count == 1
