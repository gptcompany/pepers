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
        """Single engine valid → VALID."""
        result = apply_consensus([_engine_ok("sympy")])
        assert result.outcome == ConsensusOutcome.VALID
        assert result.engine_count == 1

    def test_single_engine_invalid(self):
        """Single engine invalid → INVALID."""
        result = apply_consensus([_engine_ok("sympy", valid=False)])
        assert result.outcome == ConsensusOutcome.INVALID

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
        """Three engines, 2 valid + 1 error → PARTIAL."""
        result = apply_consensus([
            _engine_ok("sympy"),
            _engine_ok("maxima"),
            _engine_err("matlab"),
        ])
        assert result.outcome == ConsensusOutcome.PARTIAL


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
        error = urllib.error.HTTPError(
            "http://localhost:8769/validate", 400, "Bad Request",
            {}, MagicMock(read=MagicMock(return_value=b'{"error": "invalid latex"}')),
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


class TestCASServiceError:
    """Tests for CASServiceError exception."""

    def test_is_exception(self):
        assert issubclass(CASServiceError, Exception)

    def test_message(self):
        err = CASServiceError("test error")
        assert str(err) == "test error"
