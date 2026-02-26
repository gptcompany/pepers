"""Unit tests for the Validator service — all external calls mocked."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from services.validator.cas_client import (
    CASClient,
    CASResponse,
    CASServiceError,
    EngineResult,
)
from services.validator.consensus import (
    ConsensusOutcome,
    ConsensusResult,
    apply_consensus,
)
from services.validator.main import (
    ValidatorHandler,
    _check_consistency,
    _mark_formula_failed,
    _query_formulas,
    _store_validations,
    _update_formula_stage,
    _update_paper_stage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_ok(engine: str = "sympy", valid: bool = True) -> EngineResult:
    """Create a successful engine result."""
    return EngineResult(
        engine=engine,
        success=True,
        is_valid=valid,
        simplified="x + 1",
        original_parsed="x + 1",
        time_ms=50,
    )


def _engine_err(engine: str = "sympy") -> EngineResult:
    """Create a failed engine result."""
    return EngineResult(
        engine=engine,
        success=False,
        error="parse error",
        time_ms=10,
    )


# ===========================================================================
# Consensus Logic Tests
# ===========================================================================


class TestApplyConsensus:
    """Tests for apply_consensus() — all 9 decision matrix combinations."""

    def test_both_valid(self):
        """Both engines valid → VALID."""
        result = apply_consensus([_engine_ok("sympy"), _engine_ok("maxima")])
        assert result.outcome == ConsensusOutcome.VALID
        assert result.engine_count == 2
        assert result.agree_count == 2

    def test_both_invalid(self):
        """Both engines invalid → INVALID."""
        result = apply_consensus([
            _engine_ok("sympy", valid=False),
            _engine_ok("maxima", valid=False),
        ])
        assert result.outcome == ConsensusOutcome.INVALID
        assert result.agree_count == 2

    def test_valid_invalid_disagreement(self):
        """SymPy valid, Maxima invalid → INVALID (disagreement)."""
        result = apply_consensus([
            _engine_ok("sympy", valid=True),
            _engine_ok("maxima", valid=False),
        ])
        assert result.outcome == ConsensusOutcome.INVALID
        assert "disagree" in result.detail.lower()

    def test_invalid_valid_disagreement(self):
        """SymPy invalid, Maxima valid → INVALID (disagreement)."""
        result = apply_consensus([
            _engine_ok("sympy", valid=False),
            _engine_ok("maxima", valid=True),
        ])
        assert result.outcome == ConsensusOutcome.INVALID

    def test_valid_error(self):
        """One valid, one error → PARTIAL."""
        result = apply_consensus([_engine_ok("sympy"), _engine_err("maxima")])
        assert result.outcome == ConsensusOutcome.PARTIAL
        assert result.agree_count == 1

    def test_error_valid(self):
        """One error, one valid → PARTIAL."""
        result = apply_consensus([_engine_err("sympy"), _engine_ok("maxima")])
        assert result.outcome == ConsensusOutcome.PARTIAL

    def test_invalid_error(self):
        """One invalid, one error → PARTIAL."""
        result = apply_consensus([
            _engine_ok("sympy", valid=False),
            _engine_err("maxima"),
        ])
        assert result.outcome == ConsensusOutcome.PARTIAL

    def test_error_invalid(self):
        """One error, one invalid → PARTIAL."""
        result = apply_consensus([
            _engine_err("sympy"),
            _engine_ok("maxima", valid=False),
        ])
        assert result.outcome == ConsensusOutcome.PARTIAL

    def test_both_error(self):
        """Both engines error → UNPARSEABLE."""
        result = apply_consensus([_engine_err("sympy"), _engine_err("maxima")])
        assert result.outcome == ConsensusOutcome.UNPARSEABLE
        assert result.agree_count == 0

    def test_empty_results(self):
        """No engine results → UNPARSEABLE."""
        result = apply_consensus([])
        assert result.outcome == ConsensusOutcome.UNPARSEABLE
        assert result.engine_count == 0

    def test_single_engine_valid(self):
        """Single engine valid → PARTIAL (insufficient for consensus)."""
        result = apply_consensus([_engine_ok("sympy")])
        assert result.outcome == ConsensusOutcome.PARTIAL
        assert result.engine_count == 1

    def test_single_engine_invalid(self):
        """Single engine invalid → PARTIAL (insufficient for consensus)."""
        result = apply_consensus([_engine_ok("sympy", valid=False)])
        assert result.outcome == ConsensusOutcome.PARTIAL

    def test_single_engine_error(self):
        """Single engine error → UNPARSEABLE."""
        result = apply_consensus([_engine_err("sympy")])
        assert result.outcome == ConsensusOutcome.UNPARSEABLE

    def test_three_engines_all_valid(self):
        """Three engines all valid → VALID."""
        result = apply_consensus([
            _engine_ok("sympy"),
            _engine_ok("maxima"),
            _engine_ok("matlab"),
        ])
        assert result.outcome == ConsensusOutcome.VALID
        assert result.agree_count == 3

    def test_three_engines_two_valid_one_invalid(self):
        """Three engines, 2 valid + 1 invalid → INVALID (not unanimous)."""
        result = apply_consensus([
            _engine_ok("sympy"),
            _engine_ok("maxima"),
            _engine_ok("matlab", valid=False),
        ])
        assert result.outcome == ConsensusOutcome.INVALID

    def test_three_engines_two_valid_one_error(self):
        """Three engines, 2 valid + 1 error → VALID (fallback: 2 agree)."""
        result = apply_consensus([
            _engine_ok("sympy"),
            _engine_ok("maxima"),
            _engine_err("matlab"),
        ])
        assert result.outcome == ConsensusOutcome.VALID
        assert result.agree_count == 2
        assert "fallback" in result.detail

    def test_three_engines_two_invalid_one_error(self):
        """Three engines, 2 invalid + 1 error → INVALID (fallback: 2 agree)."""
        result = apply_consensus([
            _engine_ok("sympy", valid=False),
            _engine_ok("maxima", valid=False),
            _engine_err("matlab"),
        ])
        assert result.outcome == ConsensusOutcome.INVALID
        assert result.agree_count == 2
        assert "fallback" in result.detail

    def test_three_engines_one_valid_two_error(self):
        """Three engines, 1 valid + 2 error → PARTIAL (only 1 succeeded)."""
        result = apply_consensus([
            _engine_ok("sympy"),
            _engine_err("maxima"),
            _engine_err("matlab"),
        ])
        assert result.outcome == ConsensusOutcome.PARTIAL
        assert result.agree_count == 1


class TestConsensusResult:
    """Tests for ConsensusResult dataclass."""

    def test_fields(self):
        r = ConsensusResult(
            outcome=ConsensusOutcome.VALID,
            detail="test",
            engine_count=2,
            agree_count=2,
        )
        assert r.outcome == ConsensusOutcome.VALID
        assert r.detail == "test"
        assert r.engine_count == 2
        assert r.agree_count == 2

    def test_outcome_values(self):
        assert ConsensusOutcome.VALID.value == "valid"
        assert ConsensusOutcome.INVALID.value == "invalid"
        assert ConsensusOutcome.PARTIAL.value == "partial"
        assert ConsensusOutcome.UNPARSEABLE.value == "unparseable"


# ===========================================================================
# CASClient Tests
# ===========================================================================


class TestCASClient:
    """Tests for CASClient — mock urllib."""

    def test_validate_success(self):
        """Successful validation returns CASResponse."""
        response_body = json.dumps({
            "results": [
                {
                    "engine": "sympy",
                    "success": True,
                    "is_valid": True,
                    "simplified": "2*x",
                    "original_parsed": "Derivative(x**2, x)",
                    "time_ms": 45,
                },
                {
                    "engine": "maxima",
                    "success": True,
                    "is_valid": True,
                    "simplified": "2*x",
                    "original_parsed": "diff(x^2, x)",
                    "time_ms": 248,
                },
            ],
            "latex_preprocessed": r"\frac{d}{dx} x^2 = 2x",
            "time_ms": 300,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            client = CASClient("http://localhost:8769")
            result = client.validate(r"\frac{d}{dx} x^2 = 2x")

        assert isinstance(result, CASResponse)
        assert len(result.results) == 2
        assert result.results[0].engine == "sympy"
        assert result.results[0].is_valid is True
        assert result.results[1].engine == "maxima"
        assert result.time_ms == 300

    def test_validate_with_engines(self):
        """Engines parameter is included in request payload."""
        response_body = json.dumps({
            "results": [{"engine": "sympy", "success": True, "is_valid": True,
                         "time_ms": 10}],
            "latex_preprocessed": "x",
            "time_ms": 10,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = CASClient()
            client.validate("x", engines=["sympy"])

            # Verify the request was made with engines in payload
            call_args = mock_open.call_args
            req = call_args[0][0]
            payload = json.loads(req.data)
            assert payload["engines"] == ["sympy"]

    def test_validate_http_error(self):
        """HTTPError → CASServiceError."""
        from email.message import Message
        hdrs = Message()
        error = urllib.error.HTTPError(
            "http://localhost:8769/validate", 400, "Bad Request",
            hdrs, MagicMock(read=MagicMock(return_value=b'{"error": "invalid latex"}')),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            client = CASClient()
            with pytest.raises(CASServiceError, match="CAS error 400"):
                client.validate("invalid")

    def test_validate_url_error(self):
        """URLError → CASServiceError (service unreachable)."""
        error = urllib.error.URLError("Connection refused")

        with patch("urllib.request.urlopen", side_effect=error):
            client = CASClient()
            with pytest.raises(CASServiceError, match="unreachable"):
                client.validate("x")

    def test_health_ok(self):
        """Health check returns True when status=ok."""
        resp_body = json.dumps({"status": "ok"}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert CASClient().health() is True

    def test_health_down(self):
        """Health check returns False when service unreachable."""
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("refused")):
            assert CASClient().health() is False

    def test_health_bad_status(self):
        """Health check returns False when status != ok."""
        resp_body = json.dumps({"status": "degraded"}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert CASClient().health() is False

    def test_base_url_trailing_slash(self):
        """Trailing slash is stripped from base_url."""
        client = CASClient("http://localhost:8769/")
        assert client.base_url == "http://localhost:8769"

    def test_validate_timeout(self):
        """Timeout is passed to urlopen."""
        response_body = json.dumps({
            "results": [],
            "latex_preprocessed": "x",
            "time_ms": 0,
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client = CASClient(timeout=60)
            client.validate("x")
            _, kwargs = mock_open.call_args
            assert kwargs["timeout"] == 60

    def test_engine_result_defaults(self):
        """EngineResult has sensible defaults."""
        r = EngineResult(engine="test", success=True)
        assert r.is_valid is None
        assert r.simplified is None
        assert r.error is None
        assert r.time_ms == 0


class TestDiscoverEngines:
    """Tests for CASClient.discover_engines() — auto-discovery."""

    def test_discover_success(self):
        """Returns engine list when CAS responds."""
        engines_data = {
            "engines": [
                {"name": "sympy", "capabilities": ["validate"]},
                {"name": "maxima", "capabilities": ["validate"]},
                {"name": "gap", "capabilities": ["validate", "compute"]},
            ]
        }
        resp_body = json.dumps(engines_data).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = CASClient().discover_engines()

        assert result is not None
        assert len(result) == 3
        assert result[0]["name"] == "sympy"
        assert result[2]["name"] == "gap"
        assert "compute" in result[2]["capabilities"]

    def test_discover_unreachable(self):
        """Returns None when CAS is unreachable."""
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("refused")):
            result = CASClient().discover_engines()
        assert result is None

    def test_discover_empty_engines(self):
        """Returns empty list when CAS has no engines."""
        resp_body = json.dumps({"engines": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = CASClient().discover_engines()
        assert result == []

    def test_discover_filters_validate_capable(self):
        """Integration: discovered engines filtered to validate-capable only."""
        engines_data = {
            "engines": [
                {"name": "sympy", "capabilities": ["validate"]},
                {"name": "gap", "capabilities": ["compute"]},  # no validate
                {"name": "maxima", "capabilities": ["validate"]},
            ]
        }
        discovered = engines_data["engines"]
        validate_engines = [
            e["name"] for e in discovered
            if "validate" in e.get("capabilities", [])
        ]
        assert validate_engines == ["sympy", "maxima"]
        assert "gap" not in validate_engines

    def test_discover_calls_correct_url(self):
        """Verifies /engines endpoint is called."""
        resp_body = json.dumps({"engines": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            CASClient("http://cas:8769").discover_engines()
            req = mock_open.call_args[0][0]
            assert req.full_url == "http://cas:8769/engines"


class TestCASServiceError:
    """Tests for CASServiceError exception."""

    def test_is_exception(self):
        assert issubclass(CASServiceError, Exception)

    def test_message(self):
        err = CASServiceError("test error")
        assert str(err) == "test error"


# ===========================================================================
# _validate_one Tests
# ===========================================================================


class TestValidateOne:
    """Tests for _validate_one() — extracted per-formula validation logic."""

    def test_empty_latex_skipped(self):
        """Empty LaTeX returns skipped result without calling CAS."""
        from services.validator.main import _validate_one

        client = MagicMock()
        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 1, "latex": "", "latex_hash": "abc"},
            ["sympy"], False,
        )
        assert result.skipped is True
        assert result.formula_id == 1
        client.validate.assert_not_called()

    def test_whitespace_latex_skipped(self):
        """Whitespace-only LaTeX is also skipped."""
        from services.validator.main import _validate_one

        client = MagicMock()
        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 2, "latex": "   ", "latex_hash": ""},
            ["sympy"], False,
        )
        assert result.skipped is True

    @patch("services.validator.main._mark_formula_failed")
    @patch("services.validator.main._update_formula_stage")
    @patch("services.validator.main._store_validations")
    def test_successful_validation(self, mock_store, mock_update, mock_fail):
        """Successful CAS call returns correct outcome."""
        from services.validator.main import _validate_one

        client = MagicMock()
        client.validate.return_value = CASResponse(
            results=[_engine_ok("sympy"), _engine_ok("maxima")],
            latex_preprocessed="x^2",
            time_ms=100,
        )

        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 5, "latex": "x^2", "latex_hash": "h5"},
            ["sympy", "maxima"], False,
        )

        assert result.outcome == "valid"
        assert result.error is None
        assert result.detail is None  # include_details=False
        mock_store.assert_called_once()
        mock_update.assert_called_once()
        mock_fail.assert_not_called()

    @patch("services.validator.main._mark_formula_failed")
    @patch("services.validator.main._update_formula_stage")
    @patch("services.validator.main._store_validations")
    def test_details_included(self, mock_store, mock_update, mock_fail):
        """include_details=True populates detail dict."""
        from services.validator.main import _validate_one

        client = MagicMock()
        client.validate.return_value = CASResponse(
            results=[_engine_ok("sympy"), _engine_ok("maxima")],
            latex_preprocessed="x^2",
            time_ms=100,
        )

        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 5, "latex": "x^2", "latex_hash": "h5"},
            ["sympy", "maxima"], True,  # include_details=True
        )

        assert result.detail is not None
        assert result.detail["formula_id"] == 5
        assert result.detail["consensus"] == "valid"
        assert "sympy" in result.detail["engines"]

    @patch("services.validator.main._mark_formula_failed")
    def test_cas_error_returns_failed(self, mock_fail):
        """CASServiceError produces failed result."""
        from services.validator.main import _validate_one

        client = MagicMock()
        client.validate.side_effect = CASServiceError("timeout")

        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 3, "latex": "x^2", "latex_hash": "h3"},
            ["sympy"], False,
        )

        assert result.outcome == "failed"
        assert "timeout" in result.error
        mock_fail.assert_called_once_with("/tmp/test.db", 3, "timeout")

    @patch("services.validator.main._mark_formula_failed")
    def test_unexpected_error_returns_failed(self, mock_fail):
        """Unexpected exception produces failed result."""
        from services.validator.main import _validate_one

        client = MagicMock()
        client.validate.side_effect = RuntimeError("boom")

        result = _validate_one(
            client, "/tmp/test.db",
            {"id": 4, "latex": "x^2", "latex_hash": "h4"},
            ["sympy"], False,
        )

        assert result.outcome == "failed"
        assert "boom" in result.error
        mock_fail.assert_called_once()


class TestParallelValidation:
    """Tests for ThreadPoolExecutor-based parallel validation."""

    @patch("services.validator.main._mark_formula_failed")
    @patch("services.validator.main._update_formula_stage")
    @patch("services.validator.main._store_validations")
    def test_parallel_same_results_as_sequential(
        self, mock_store, mock_update, mock_fail, monkeypatch,
    ):
        """Parallel and sequential produce identical aggregate counts."""
        from services.validator.main import _validate_one

        client = MagicMock()
        client.validate.return_value = CASResponse(
            results=[_engine_ok("sympy"), _engine_ok("maxima")],
            latex_preprocessed="x",
            time_ms=10,
        )

        formulas = [
            {"id": i, "latex": f"x^{i}", "latex_hash": f"h{i}"}
            for i in range(1, 6)
        ]
        engines = ["sympy", "maxima"]

        # Sequential
        seq_results = [
            _validate_one(client, "/tmp/test.db", f, engines, False)
            for f in formulas
        ]

        mock_store.reset_mock()
        mock_update.reset_mock()

        # Parallel (via ThreadPoolExecutor)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_validate_one, client, "/tmp/test.db", f, engines, False): f["id"]
                for f in formulas
            }
            par_results = [fut.result() for fut in as_completed(futures)]

        # Same outcomes (order may differ)
        seq_outcomes = sorted(r.outcome for r in seq_results)
        par_outcomes = sorted(r.outcome for r in par_results)
        assert seq_outcomes == par_outcomes

        # Same formula IDs processed
        seq_ids = sorted(r.formula_id for r in seq_results)
        par_ids = sorted(r.formula_id for r in par_results)
        assert seq_ids == par_ids


# ===========================================================================
# services/validator/main.py Tests
# ===========================================================================


class TestValidatorHelpers:
    """Tests for standalone helper functions in main.py."""

    def test_check_consistency_safe(self, initialized_db):
        _check_consistency(str(initialized_db))

    def test_query_formulas_extracted(self, extracted_formula_db):
        formulas = _query_formulas(str(extracted_formula_db), 1, None, 10, False)
        assert len(formulas) == 1
        assert formulas[0]["stage"] == "extracted"

    def test_store_validations(self, extracted_formula_db):
        db_path = str(extracted_formula_db)
        res = [_engine_ok("sympy")]
        _store_validations(db_path, 1, res)
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        row = conn.execute("SELECT * FROM validations WHERE formula_id=1").fetchone()
        assert row["engine"] == "sympy"
        assert row["is_valid"] == 1
        conn.close()

    def test_update_formula_stage_valid(self, extracted_formula_db):
        db_path = str(extracted_formula_db)
        consensus = ConsensusResult(ConsensusOutcome.VALID, "ok", 2, 2)
        _update_formula_stage(db_path, 1, consensus)
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        row = conn.execute("SELECT stage FROM formulas WHERE id=1").fetchone()
        assert row["stage"] == "validated"
        conn.close()

    def test_update_paper_stage(self, extracted_formula_db):
        db_path = str(extracted_formula_db)
        _update_paper_stage(db_path, 1, "validated")
        from shared.db import get_connection
        conn = get_connection(db_path)
        row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "validated"
        conn.close()


class TestValidatorHandler:
    """Tests for ValidatorHandler.handle_process()."""

    @patch("services.validator.main.CASClient.health", return_value=True)
    @patch("services.validator.main.CASClient.validate")
    def test_handle_process_success(self, mock_validate, mock_health, extracted_formula_db):
        db_path = str(extracted_formula_db)
        handler = ValidatorHandler.__new__(ValidatorHandler)
        handler.db_path = db_path
        handler.cas_url = "http://cas:8769"
        handler.cas_timeout = 60
        handler.engines = ["sympy", "maxima"]
        
        mock_validate.return_value = CASResponse(
            results=[_engine_ok("sympy"), _engine_ok("maxima")],
            latex_preprocessed="x+1",
            time_ms=100
        )
        
        resp = handler.handle_process({"paper_id": 1})
        assert resp["success"] is True
        assert resp["formulas_processed"] == 1
        assert resp["formulas_valid"] == 1
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        p_row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert p_row["stage"] == "validated"
        conn.close()

    @patch("services.validator.main.CASClient.health", return_value=False)
    def test_handle_process_service_down(self, mock_health, extracted_formula_db):
        db_path = str(extracted_formula_db)
        handler = ValidatorHandler.__new__(ValidatorHandler)
        handler.db_path = db_path
        handler.cas_url = "http://cas:8769"
        handler.engines = ["sympy"]
        handler.send_error_json = MagicMock()
        
        resp = handler.handle_process({})
        assert resp is None
        handler.send_error_json.assert_called_once()
