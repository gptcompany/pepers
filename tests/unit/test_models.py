"""Unit tests for shared/models.py — Pydantic data models."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from shared.models import (
    ErrorResponse,
    Formula,
    GeneratedCode,
    Paper,
    PipelineStage,
    ProcessRequest,
    ProcessResponse,
    ServiceStatus,
    Validation,
    _parse_json_dict,
    _parse_json_list,
)


class TestPipelineStage:
    """Tests for PipelineStage enum."""

    def test_all_stages_exist(self):
        stages = [s.value for s in PipelineStage]
        assert stages == [
            "discovered", "analyzed", "extracted",
            "validated", "codegen", "complete", "failed",
        ]

    def test_string_value(self):
        assert PipelineStage.DISCOVERED == "discovered"

    def test_from_string(self):
        stage = PipelineStage("discovered")
        assert stage == PipelineStage.DISCOVERED

    def test_invalid_stage(self):
        with pytest.raises(ValueError):
            PipelineStage("nonexistent")


class TestJsonParsers:
    """Tests for _parse_json_list and _parse_json_dict."""

    def test_parse_list_from_none(self):
        assert _parse_json_list(None) == []

    def test_parse_list_from_string(self):
        assert _parse_json_list('["a", "b"]') == ["a", "b"]

    def test_parse_list_from_list(self):
        assert _parse_json_list(["a", "b"]) == ["a", "b"]

    def test_parse_list_from_tuple(self):
        assert _parse_json_list(("a", "b")) == ["a", "b"]

    def test_parse_list_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_list("not json")

    def test_parse_dict_from_none(self):
        assert _parse_json_dict(None) is None

    def test_parse_dict_from_string(self):
        assert _parse_json_dict('{"key": "val"}') == {"key": "val"}

    def test_parse_dict_from_dict(self):
        assert _parse_json_dict({"key": "val"}) == {"key": "val"}

    def test_parse_dict_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_dict("not json")


class TestPaper:
    """Tests for Paper model."""

    def test_minimal_creation(self):
        p = Paper(arxiv_id="2401.00001", title="Test Paper")
        assert p.arxiv_id == "2401.00001"
        assert p.title == "Test Paper"
        assert p.stage == PipelineStage.DISCOVERED
        assert p.authors == []
        assert p.categories == []

    def test_full_creation(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test Paper",
            abstract="Abstract text",
            authors=["Alice", "Bob"],
            categories=["q-fin.PM"],
            doi="10.1234/test",
            citation_count=42,
            open_access=True,
            crossref_data={"publisher": "Test"},
            stage=PipelineStage.ANALYZED,
            score=0.85,
        )
        assert p.authors == ["Alice", "Bob"]
        assert p.crossref_data == {"publisher": "Test"}
        assert p.score == 0.85

    def test_json_string_authors(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test",
            authors='["Alice", "Bob"]',  # type: ignore[arg-type]
        )
        assert p.authors == ["Alice", "Bob"]

    def test_json_string_categories(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test",
            categories='["q-fin.PM", "stat.ML"]',  # type: ignore[arg-type]
        )
        assert p.categories == ["q-fin.PM", "stat.ML"]

    def test_json_string_fields_of_study(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test",
            fields_of_study='["Mathematics", "Computer Science"]',  # type: ignore[arg-type]
        )
        assert p.fields_of_study == ["Mathematics", "Computer Science"]

    def test_json_string_crossref_data(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test",
            crossref_data='{"publisher": "Springer"}',  # type: ignore[arg-type]
        )
        assert p.crossref_data == {"publisher": "Springer"}

    def test_none_authors_becomes_empty_list(self):
        p = Paper(arxiv_id="2401.00001", title="Test", authors=None)  # type: ignore[arg-type]
        assert p.authors == []

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Paper()  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        p = Paper(
            arxiv_id="2401.00001",
            title="Test",
            authors=["Alice"],
            crossref_data={"key": "val"},
        )
        data = p.model_dump()
        p2 = Paper(**data)
        assert p2.arxiv_id == p.arxiv_id
        assert p2.authors == p.authors


class TestFormula:
    """Tests for Formula model."""

    def test_auto_hash_computation(self):
        f = Formula(paper_id=1, latex=r"x^2 + 1")
        expected_hash = hashlib.sha256(r"x^2 + 1".encode()).hexdigest()
        assert f.latex_hash == expected_hash

    def test_hash_not_overwritten_when_provided(self):
        f = Formula(paper_id=1, latex=r"x^2", latex_hash="custom_hash")
        assert f.latex_hash == "custom_hash"

    def test_same_latex_same_hash(self):
        f1 = Formula(paper_id=1, latex=r"E = mc^2")
        f2 = Formula(paper_id=2, latex=r"E = mc^2")
        assert f1.latex_hash == f2.latex_hash

    def test_different_latex_different_hash(self):
        f1 = Formula(paper_id=1, latex=r"x^2")
        f2 = Formula(paper_id=1, latex=r"x^3")
        assert f1.latex_hash != f2.latex_hash

    def test_default_stage(self):
        f = Formula(paper_id=1, latex="x")
        assert f.stage == PipelineStage.EXTRACTED

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Formula()  # type: ignore[call-arg]


class TestValidation:
    """Tests for Validation model."""

    def test_creation(self):
        v = Validation(
            formula_id=1, engine="sympy", is_valid=True, result="OK", time_ms=150
        )
        assert v.engine == "sympy"
        assert v.is_valid is True
        assert v.time_ms == 150

    def test_is_valid_can_be_none(self):
        v = Validation(formula_id=1, engine="maxima")
        assert v.is_valid is None


class TestGeneratedCode:
    """Tests for GeneratedCode model."""

    def test_creation(self):
        gc = GeneratedCode(
            formula_id=1,
            language="python",
            code="import sympy\nx = sympy.Symbol('x')",
            metadata={"compiler": "sympy"},
        )
        assert gc.language == "python"
        assert gc.metadata == {"compiler": "sympy"}

    def test_json_string_metadata(self):
        gc = GeneratedCode(
            formula_id=1,
            language="rust",
            code="fn main() {}",
            metadata='{"toolchain": "nightly"}',  # type: ignore[arg-type]
        )
        assert gc.metadata == {"toolchain": "nightly"}

    def test_none_metadata(self):
        gc = GeneratedCode(formula_id=1, language="python", code="x = 1")
        assert gc.metadata is None

    def test_default_stage(self):
        gc = GeneratedCode(formula_id=1, language="python", code="x = 1")
        assert gc.stage == PipelineStage.CODEGEN


class TestServiceStatus:
    """Tests for ServiceStatus model."""

    def test_creation(self):
        s = ServiceStatus(service="discovery", version="0.1.0", uptime_seconds=3600.5)
        assert s.status == "ok"
        assert s.service == "discovery"

    def test_default_status(self):
        s = ServiceStatus(service="test", version="1.0")
        assert s.status == "ok"
        assert s.uptime_seconds == 0.0


class TestProcessRequestResponse:
    """Tests for ProcessRequest and ProcessResponse."""

    def test_request_defaults(self):
        r = ProcessRequest()
        assert r.paper_id is None
        assert r.force is False

    def test_response_creation(self):
        r = ProcessResponse(success=True, service="test", time_ms=42)
        assert r.success is True
        assert r.time_ms == 42


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_creation(self):
        e = ErrorResponse(error="Not found", code="NOT_FOUND")
        assert e.error == "Not found"
        assert e.details is None

    def test_with_details(self):
        e = ErrorResponse(error="Bad", code="BAD", details={"field": "x"})
        assert e.details == {"field": "x"}

    def test_serialization(self):
        e = ErrorResponse(error="test", code="TEST_CODE")
        data = e.model_dump()
        assert data["error"] == "test"
        assert data["code"] == "TEST_CODE"
