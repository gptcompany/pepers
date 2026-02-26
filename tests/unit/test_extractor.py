"""Unit tests for the Extractor service — all external calls mocked."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.extractor.pdf import (
    EXPORT_BASE,
    USER_AGENT,
    create_session,
    download_pdf,
    get_pdf_url,
)
from services.extractor.rag_client import (
    check_service,
    poll_job,
    process_paper,
    read_markdown,
    submit_pdf,
)
from services.extractor.latex import (
    CONTEXT_WINDOW,
    MIN_FORMULA_LENGTH,
    expand_custom_notations,
    extract_context,
    extract_formulas,
    filter_formulas,
    formulas_to_models,
    is_nontrivial,
)
from services.extractor.main import (
    ExtractorHandler,
    _check_consistency,
    _load_notations,
    _mark_failed,
    _query_papers,
    _store_results,
)
from shared.models import Formula, Paper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(**kwargs) -> Paper:
    """Create a Paper with sensible defaults."""
    defaults = {
        "id": 1,
        "arxiv_id": "2401.00001",
        "title": "Test Paper",
        "abstract": "Test abstract.",
        "authors": '["Alice"]',
        "categories": '["q-fin.PM"]',
        "doi": None,
        "pdf_url": None,
        "published_date": "2024-01-15",
        "stage": "analyzed",
    }
    defaults.update(kwargs)
    return Paper(**defaults)


# ---------------------------------------------------------------------------
# TestGetPdfUrl
# ---------------------------------------------------------------------------


class TestGetPdfUrl:
    """Tests for get_pdf_url()."""

    def test_uses_stored_pdf_url(self):
        paper = _make_paper(pdf_url="https://export.arxiv.org/pdf/2401.00001")
        assert get_pdf_url(paper) == "https://export.arxiv.org/pdf/2401.00001"

    def test_rewrites_http_to_https_export(self):
        paper = _make_paper(pdf_url="http://arxiv.org/pdf/2401.00001")
        url = get_pdf_url(paper)
        assert url == "https://export.arxiv.org/pdf/2401.00001"

    def test_rewrites_https_to_export(self):
        paper = _make_paper(pdf_url="https://arxiv.org/pdf/2401.00001")
        url = get_pdf_url(paper)
        assert url == "https://export.arxiv.org/pdf/2401.00001"

    def test_fallback_to_constructed_url(self):
        paper = _make_paper(pdf_url=None)
        url = get_pdf_url(paper)
        assert url == f"{EXPORT_BASE}/2401.00001"


# ---------------------------------------------------------------------------
# TestCreateSession
# ---------------------------------------------------------------------------


class TestCreateSession:
    """Tests for create_session()."""

    def test_session_has_user_agent(self):
        session = create_session()
        assert session.headers.get("User-Agent") == USER_AGENT

    def test_session_has_retry_strategy(self):
        session = create_session()
        adapter = session.get_adapter("https://example.com")
        assert adapter.max_retries.total == 3  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# TestDownloadPdf
# ---------------------------------------------------------------------------


class TestDownloadPdf:
    """Tests for download_pdf() — mock requests.Session."""

    def test_cache_hit_skips_download(self, tmp_path):
        """Existing file >1000 bytes → return immediately, no HTTP call."""
        paper = _make_paper()
        pdf_file = tmp_path / "2401.00001.pdf"
        pdf_file.write_bytes(b"x" * 2000)

        mock_session = MagicMock()
        result = download_pdf(paper, tmp_path, mock_session)
        assert result == pdf_file
        mock_session.get.assert_not_called()

    def test_successful_download(self, tmp_path):
        paper = _make_paper()
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.return_value = [b"%PDF-1.4 fake content" * 100]
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        result = download_pdf(paper, tmp_path, mock_session)
        assert result.exists()
        assert result.stat().st_size > 0
        assert result.name == "2401.00001.pdf"

    def test_non_pdf_content_type_raises(self, tmp_path):
        paper = _make_paper()
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Expected PDF"):
            download_pdf(paper, tmp_path, mock_session)

    def test_creates_dest_dir(self, tmp_path):
        paper = _make_paper()
        dest_dir = tmp_path / "subdir" / "pdfs"
        assert not dest_dir.exists()

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.return_value = [b"%PDF-1.4 data" * 100]
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        result = download_pdf(paper, dest_dir, mock_session)
        assert dest_dir.exists()
        assert result.exists()

    def test_slash_in_arxiv_id_safe_name(self, tmp_path):
        """Old-style arxiv IDs like hep-ph/0601001 → hep-ph_0601001.pdf."""
        paper = _make_paper(arxiv_id="hep-ph/0601001")
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.iter_content.return_value = [b"%PDF data" * 200]
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        result = download_pdf(paper, tmp_path, mock_session)
        assert result.name == "hep-ph_0601001.pdf"


# ---------------------------------------------------------------------------
# TestCheckService
# ---------------------------------------------------------------------------


class TestCheckService:
    """Tests for check_service() — mock urllib.request.urlopen."""

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_service_healthy(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "ok",
            "circuit_breaker": {"state": "closed"},
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = check_service("http://localhost:8767")
        assert result["status"] == "ok"

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_circuit_breaker_open(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "degraded",
            "circuit_breaker": {"state": "open"},
        }).encode()
        mock_urlopen.return_value = mock_resp

        with pytest.raises(RuntimeError, match="circuit breaker is open"):
            check_service("http://localhost:8767")

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_service_unreachable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(urllib.error.URLError):
            check_service("http://localhost:8767")


# ---------------------------------------------------------------------------
# TestSubmitPdf
# ---------------------------------------------------------------------------


class TestSubmitPdf:
    """Tests for submit_pdf() — mock urllib.request.urlopen."""

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_cached_result(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "cached": True,
            "output_dir": "/workspace/1TB/rag/paper1",
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = submit_pdf(Path("/tmp/test.pdf"), "2401.00001")
        assert result["cached"] is True
        assert "result" in result

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_new_job_queued(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "job_id": "job-abc-123",
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = submit_pdf(Path("/tmp/test.pdf"), "2401.00001")
        assert result["cached"] is False
        assert result["job_id"] == "job-abc-123"

    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_request_format(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"job_id": "j1"}).encode()
        mock_urlopen.return_value = mock_resp

        submit_pdf(Path("/data/pdfs/test.pdf"), "2401.00001", "http://rag:8767")
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://rag:8767/process"
        body = json.loads(req.data.decode())
        assert body["pdf_path"] == "/data/pdfs/test.pdf"
        assert body["paper_id"] == "2401.00001"


# ---------------------------------------------------------------------------
# TestPollJob
# ---------------------------------------------------------------------------


class TestPollJob:
    """Tests for poll_job() — mock urllib.request.urlopen + time.sleep."""

    @patch("services.extractor.rag_client.time.sleep")
    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_completed_immediately(self, mock_urlopen, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "completed",
            "result": {"output_dir": "/workspace/1TB/rag/out"},
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = poll_job("job-1")
        assert result["output_dir"] == "/workspace/1TB/rag/out"
        mock_sleep.assert_not_called()

    @patch("services.extractor.rag_client.time.sleep")
    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_completed_after_retry(self, mock_urlopen, mock_sleep):
        pending = MagicMock()
        pending.read.return_value = json.dumps({
            "status": "processing",
        }).encode()

        completed = MagicMock()
        completed.read.return_value = json.dumps({
            "status": "completed",
            "result": {"output_dir": "/out"},
        }).encode()

        mock_urlopen.side_effect = [pending, pending, completed]

        result = poll_job("job-1", timeout=600, interval=1)
        assert result["output_dir"] == "/out"
        assert mock_sleep.call_count == 2

    @patch("services.extractor.rag_client.time.sleep")
    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_job_failed(self, mock_urlopen, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "failed",
            "error": "OOM killed",
        }).encode()
        mock_urlopen.return_value = mock_resp

        with pytest.raises(RuntimeError, match="failed.*OOM killed"):
            poll_job("job-1")

    @patch("services.extractor.rag_client.time.time")
    @patch("services.extractor.rag_client.time.sleep")
    @patch("services.extractor.rag_client.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen, mock_sleep, mock_time):
        # Simulate time passing beyond timeout
        mock_time.side_effect = [0, 0, 100, 200, 700]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "processing",
        }).encode()
        mock_urlopen.return_value = mock_resp

        with pytest.raises(TimeoutError, match="timed out"):
            poll_job("job-1", timeout=600, interval=1)


# ---------------------------------------------------------------------------
# TestReadMarkdown
# ---------------------------------------------------------------------------


class TestReadMarkdown:
    """Tests for read_markdown() — real filesystem via tmp_path."""

    def test_reads_largest_md_file(self, tmp_path):
        (tmp_path / "small.md").write_text("small content")
        (tmp_path / "auto_paper.md").write_text("large content " * 100)

        result = read_markdown(str(tmp_path))
        assert "large content" in result

    def test_container_path_mapping_1tb(self, tmp_path):
        # Create the expected host path structure
        host_dir = tmp_path / "media" / "sam" / "1TB" / "rag" / "out"
        host_dir.mkdir(parents=True)
        (host_dir / "output.md").write_text("# Extracted text")

        # read_markdown tries path as-is first
        result = read_markdown(str(host_dir))
        assert "Extracted text" in result

    def test_container_path_mapping_3tb(self, tmp_path):
        host_dir = tmp_path / "media" / "sam" / "3TB-WDC" / "rag"
        host_dir.mkdir(parents=True)
        (host_dir / "doc.md").write_text("# 3TB content")

        result = read_markdown(str(host_dir))
        assert "3TB content" in result

    def test_no_markdown_raises(self, tmp_path):
        # Empty directory
        with pytest.raises(FileNotFoundError, match="No markdown files"):
            read_markdown(str(tmp_path))


# ---------------------------------------------------------------------------
# TestProcessPaper
# ---------------------------------------------------------------------------


class TestProcessPaper:
    """Tests for process_paper() — mock all sub-functions."""

    @patch("services.extractor.rag_client.read_markdown")
    @patch("services.extractor.rag_client.submit_pdf")
    @patch("services.extractor.rag_client.check_service")
    def test_cached_flow(self, mock_check, mock_submit, mock_read):
        mock_check.return_value = {"status": "ok"}
        mock_submit.return_value = {
            "cached": True,
            "result": {"output_dir": "/workspace/1TB/rag/cached"},
        }
        mock_read.return_value = "# Cached markdown"

        result = process_paper(Path("/tmp/test.pdf"), "2401.00001")
        assert result == "# Cached markdown"
        mock_read.assert_called_once_with("/workspace/1TB/rag/cached")

    @patch("services.extractor.rag_client.read_markdown")
    @patch("services.extractor.rag_client.poll_job")
    @patch("services.extractor.rag_client.submit_pdf")
    @patch("services.extractor.rag_client.check_service")
    def test_new_job_flow(self, mock_check, mock_submit, mock_poll, mock_read):
        mock_check.return_value = {"status": "ok"}
        mock_submit.return_value = {"cached": False, "job_id": "job-42"}
        mock_poll.return_value = {"output_dir": "/workspace/1TB/rag/new"}
        mock_read.return_value = "# New extraction"

        result = process_paper(Path("/tmp/test.pdf"), "2401.00001")
        assert result == "# New extraction"
        mock_poll.assert_called_once_with("job-42", "http://localhost:8767")

    @patch("services.extractor.rag_client.submit_pdf")
    @patch("services.extractor.rag_client.check_service")
    def test_no_output_dir_raises(self, mock_check, mock_submit):
        mock_check.return_value = {"status": "ok"}
        mock_submit.return_value = {
            "cached": True,
            "result": {"output_dir": ""},
        }

        with pytest.raises(RuntimeError, match="No output_dir"):
            process_paper(Path("/tmp/test.pdf"), "2401.00001")


# ---------------------------------------------------------------------------
# TestExtractFormulas
# ---------------------------------------------------------------------------


class TestExtractFormulas:
    """Tests for extract_formulas() — pure function, no mocks needed."""

    def test_named_environment_equation(self):
        text = r"Some text \begin{equation} E = mc^2 \end{equation} more text"
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["latex"] == "E = mc^2"
        assert result[0]["formula_type"] == "display"

    def test_named_environment_align(self):
        text = r"\begin{align*} a &= b \\ c &= d \end{align*}"
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "display"
        assert "a &= b" in result[0]["latex"]

    def test_display_bracket(self):
        text = r"Formula: \[ \alpha + \beta = \gamma \]"
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "display"
        assert r"\alpha" in result[0]["latex"]

    def test_display_dollar(self):
        text = r"Formula: $$\int_0^1 f(x) dx$$"
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "display"
        assert r"\int" in result[0]["latex"]

    def test_inline_paren(self):
        text = r"The value \(\mu = 0.5\) is used."
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "inline"
        assert r"\mu" in result[0]["latex"]

    def test_inline_dollar(self):
        text = r"The ratio $\frac{a}{b}$ is important."
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "inline"
        assert r"\frac{a}{b}" in result[0]["latex"]

    def test_priority_no_overlap(self):
        """Higher-priority pattern should claim the span; lower shouldn't duplicate."""
        text = r"\begin{equation} x^2 \end{equation}"
        result = extract_formulas(text)
        # Only one match from named env; display bracket/dollar should not duplicate
        assert len(result) == 1

    def test_empty_text(self):
        assert extract_formulas("") == []

    def test_multiple_formulas_sorted_by_position(self):
        text = r"First $\alpha$ then $\beta$ finally $\gamma$."
        result = extract_formulas(text)
        assert len(result) == 3
        assert result[0]["start"] < result[1]["start"] < result[2]["start"]

    def test_math_environment_is_inline(self):
        text = r"\begin{math} x + y \end{math}"
        result = extract_formulas(text)
        assert len(result) == 1
        assert result[0]["formula_type"] == "inline"

    def test_mixed_display_and_inline(self, sample_markdown_with_formulas):
        result = extract_formulas(sample_markdown_with_formulas)
        types = {f["formula_type"] for f in result}
        assert "display" in types
        assert "inline" in types
        assert len(result) >= 5  # The sample has multiple formulas


# ---------------------------------------------------------------------------
# TestFilterFormulas
# ---------------------------------------------------------------------------


class TestFilterFormulas:
    """Tests for filter_formulas()."""

    def test_removes_trivially_short(self):
        formulas = [{"latex": "x", "formula_type": "inline", "start": 0, "end": 1}]
        assert filter_formulas(formulas) == []

    def test_removes_non_math(self):
        formulas = [{"latex": "hello world longer", "formula_type": "inline", "start": 0, "end": 10}]
        assert filter_formulas(formulas) == []

    def test_deduplicates(self):
        f = {"latex": r"\frac{a}{b}", "formula_type": "inline", "start": 0, "end": 10}
        result = filter_formulas([f, dict(f, start=20, end=30)])
        assert len(result) == 1

    def test_passes_valid_formulas(self):
        formulas = [
            {"latex": r"\frac{p}{q}", "formula_type": "display", "start": 0, "end": 15},
            {"latex": r"\sum_{i=1}^{n} x_i", "formula_type": "display", "start": 20, "end": 40},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 2

    def test_rejects_single_greek_letter(self):
        formulas = [
            {"latex": r"\mu", "formula_type": "inline", "start": 0, "end": 5},
            {"latex": r"\sigma", "formula_type": "inline", "start": 10, "end": 18},
            {"latex": r"\alpha_t", "formula_type": "inline", "start": 20, "end": 30},
            {"latex": r"\beta_{0}", "formula_type": "inline", "start": 35, "end": 45},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 0

    def test_rejects_pure_superscript(self):
        formulas = [
            {"latex": "^{1}", "formula_type": "inline", "start": 0, "end": 5},
            {"latex": "_{i}", "formula_type": "inline", "start": 10, "end": 15},
            {"latex": "^{n+1}", "formula_type": "inline", "start": 20, "end": 28},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 0

    def test_accepts_equation_with_operator(self):
        formulas = [
            {"latex": r"\frac{a}{b} + c", "formula_type": "display",
             "start": 0, "end": 20},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 1

    def test_accepts_sum_expression(self):
        formulas = [
            {"latex": r"\sum_{i=1}^{n} x_i", "formula_type": "display",
             "start": 0, "end": 25},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 1

    def test_accepts_short_formula_with_operator(self):
        """Short formula with = operator should pass despite < MIN_FORMULA_LENGTH."""
        formulas = [
            {"latex": r"a+b=c", "formula_type": "inline", "start": 0, "end": 8},
        ]
        result = filter_formulas(formulas)
        assert len(result) == 1

    def test_min_formula_length_is_10(self):
        assert MIN_FORMULA_LENGTH == 10


# ---------------------------------------------------------------------------
# TestIsNontrivial
# ---------------------------------------------------------------------------


class TestIsNontrivial:
    """Tests for is_nontrivial() — complexity heuristic."""

    def test_arithmetic_operator(self):
        assert is_nontrivial(r"a + b") is True

    def test_equals_sign(self):
        assert is_nontrivial(r"x = 1") is True

    def test_frac_operator(self):
        assert is_nontrivial(r"\frac{a}{b}") is True

    def test_sum_operator(self):
        assert is_nontrivial(r"\sum_{i=1}^{n}") is True

    def test_integral_operator(self):
        assert is_nontrivial(r"\int_0^1 f(x) dx") is True

    def test_single_greek_trivial(self):
        assert is_nontrivial(r"\mu") is False

    def test_greek_with_subscript_trivial(self):
        assert is_nontrivial(r"\sigma_{t}") is False

    def test_greek_with_superscript_trivial(self):
        assert is_nontrivial(r"\beta^{2}") is False

    def test_pure_superscript_trivial(self):
        assert is_nontrivial("^{1}") is False

    def test_pure_subscript_trivial(self):
        assert is_nontrivial("_{i}") is False

    def test_multiple_commands_nontrivial(self):
        """Two+ meaningful commands → nontrivial."""
        assert is_nontrivial(r"\sqrt{\alpha}") is True

    def test_formatting_only_trivial(self):
        """Only formatting commands don't count as nontrivial."""
        assert is_nontrivial(r"\mathbf{x}") is False


# ---------------------------------------------------------------------------
# TestExtractContext
# ---------------------------------------------------------------------------


class TestExtractContext:
    """Tests for extract_context()."""

    def test_context_window(self):
        text = "A" * 300 + "FORMULA" + "B" * 300
        start = 300
        end = 307
        ctx = extract_context(text, start, end, window=CONTEXT_WINDOW)
        # Should include chars before and after
        assert len(ctx) <= (CONTEXT_WINDOW * 2 + 7)
        assert "FORMULA" in ctx

    def test_context_at_boundaries(self):
        text = "FORMULA at start of text"
        ctx = extract_context(text, 0, 7, window=200)
        assert ctx.startswith("FORMULA")


# ---------------------------------------------------------------------------
# TestFormulasToModels
# ---------------------------------------------------------------------------


class TestFormulasToModels:
    """Tests for formulas_to_models()."""

    def test_creates_formula_models(self):
        text = "Context around " + r"\frac{a}{b}" + " formula here."
        raw = [{"latex": r"\frac{a}{b}", "formula_type": "display", "start": 15, "end": 26}]
        models = formulas_to_models(paper_id=1, text=text, raw_formulas=raw)
        assert len(models) == 1
        assert isinstance(models[0], Formula)
        assert models[0].paper_id == 1
        assert models[0].formula_type == "display"
        assert models[0].latex == r"\frac{a}{b}"

    def test_latex_hash_computed(self):
        text = "x" * 50
        raw = [{"latex": r"\alpha + \beta", "formula_type": "inline", "start": 10, "end": 25}]
        models = formulas_to_models(paper_id=1, text=text, raw_formulas=raw)
        expected_hash = hashlib.sha256(r"\alpha + \beta".encode()).hexdigest()
        assert models[0].latex_hash == expected_hash


# ---------------------------------------------------------------------------
# TestExpandCustomNotations
# ---------------------------------------------------------------------------


class TestExpandCustomNotations:
    """Tests for expand_custom_notations()."""

    def test_expand_no_args(self):
        formulas = [{"latex": r"\KL(p || q)"}]
        notations = [{"name": "KL", "body": "D_{KL}", "nargs": 0}]
        expanded = expand_custom_notations(formulas, notations)
        assert expanded[0]["latex"] == r"D_{KL}(p || q)"

    def test_expand_with_args(self):
        formulas = [{"latex": r"\prob{X}{Y}"}]
        notations = [{"name": "prob", "body": "P(#1 | #2)", "nargs": 2}]
        expanded = expand_custom_notations(formulas, notations)
        assert expanded[0]["latex"] == "P(X | Y)"

    def test_expand_multiple(self):
        formulas = [{"latex": r"\KL(p || q) + \prob{X}{Y}"}]
        notations = [
            {"name": "KL", "body": "D_{KL}", "nargs": 0},
            {"name": "prob", "body": "P(#1 | #2)", "nargs": 2},
        ]
        expanded = expand_custom_notations(formulas, notations)
        assert expanded[0]["latex"] == r"D_{KL}(p || q) + P(X | Y)"

    def test_no_notations_returns_original(self):
        formulas = [{"latex": "x^2"}]
        assert expand_custom_notations(formulas, []) == formulas


# ---------------------------------------------------------------------------
# services/extractor/main.py Tests
# ---------------------------------------------------------------------------


class TestExtractorHelpers:
    """Tests for standalone helper functions in main.py."""

    def test_check_consistency_safe(self, initialized_db):
        _check_consistency(str(initialized_db))

    def test_store_results_conflict(self, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        formula = Formula(paper_id=1, latex="x=1", formula_type="inline", context="c")
        _store_results(db_path, 1, [formula])
        # Calling again with same formula should not crash (UPDATE path)
        _store_results(db_path, 1, [formula])

    def test_load_notations(self, initialized_db):
        db_path = str(initialized_db)
        from shared.db import transaction
        with transaction(db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS custom_notations "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, body TEXT, nargs INTEGER)"
            )
            conn.execute(
                "INSERT INTO custom_notations (name, body, nargs) VALUES (?, ?, ?)",
                ("KL", "D_{KL}", 0)
            )
        notations = _load_notations(db_path)
        assert len(notations) == 1
        assert notations[0]["name"] == "KL"

    def test_query_papers_analyzed(self, analyzed_paper_db):
        papers = _query_papers(str(analyzed_paper_db), None, 10, False)
        assert len(papers) == 1
        assert papers[0]["stage"] == "analyzed"

    def test_query_papers_specific_force(self, analyzed_paper_db):
        # Force re-querying an analyzed paper
        papers = _query_papers(str(analyzed_paper_db), 1, 10, True)
        assert len(papers) == 1

    def test_store_results(self, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        formula = Formula(
            paper_id=1,
            latex=r"x^2",
            formula_type="inline",
            context="test context"
        )
        _store_results(db_path, 1, [formula])
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        p_row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert p_row["stage"] == "extracted"
        f_row = conn.execute("SELECT * FROM formulas WHERE paper_id=1").fetchone()
        assert f_row["latex"] == r"x^2"
        conn.close()

    def test_mark_failed(self, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        _mark_failed(db_path, 1, "extractor error")
        from shared.db import get_connection
        conn = get_connection(db_path)
        row = conn.execute("SELECT stage, error FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "failed"
        assert "extractor error" in row["error"]
        conn.close()

    def test_query_papers_force_includes_failed(self, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        # Mark as failed
        _mark_failed(db_path, 1, "err")
        
        # Without force: 0
        papers = _query_papers(db_path, None, 10, False)
        assert len(papers) == 0
        
        # With force + paper_id: 1
        papers = _query_papers(db_path, 1, 10, True)
        assert len(papers) == 1

    def test_check_consistency_safe(self, initialized_db):
        _check_consistency(str(initialized_db))

    def test_store_results_conflict(self, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        formula = Formula(paper_id=1, latex="x=1", formula_type="inline", context="c")
        _store_results(db_path, 1, [formula])
        # Calling again with same formula should not crash (UPDATE path)
        _store_results(db_path, 1, [formula])


class TestExtractorHandler:
    """Tests for ExtractorHandler.handle_process()."""

    @patch("services.extractor.main.pdf.create_session")
    @patch("services.extractor.main.pdf.download_pdf")
    @patch("services.extractor.main.rag_client.process_paper")
    @patch("services.extractor.main.rag_client.check_service")
    def test_handle_process_paper_level_failure(self, mock_check, mock_rag, mock_pdf, mock_session, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        handler = ExtractorHandler.__new__(ExtractorHandler)
        handler.db_path = db_path
        handler.pdf_dir = "/tmp"
        handler.download_delay = 0
        handler.rag_url = "http://rag"

        mock_check.return_value = {"status": "ok"}
        
        # PDF download fails
        mock_pdf.side_effect = Exception("Download failed")
        resp = handler.handle_process({"paper_id": 1})
        assert resp["papers_processed"] == 0
        assert resp["papers_failed"] == 1
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        row = conn.execute("SELECT stage, error FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "failed"
        assert "Download failed" in row["error"]
        conn.close()

    @patch("services.extractor.main.pdf.create_session")
    @patch("services.extractor.main.pdf.download_pdf")
    @patch("services.extractor.main.rag_client.process_paper")
    @patch("services.extractor.main.rag_client.check_service")
    def test_handle_process_success(self, mock_check, mock_rag, mock_pdf, mock_session, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        handler = ExtractorHandler.__new__(ExtractorHandler)
        handler.db_path = db_path
        handler.pdf_dir = "/tmp"
        handler.download_delay = 0
        handler.rag_url = "http://rag"

        mock_check.return_value = {"status": "ok"}
        mock_pdf.return_value = Path("/tmp/p.pdf")
        # Formula needs to be > 10 chars and have an operator to be non-trivial
        mock_rag.return_value = "$$ E = m c^2 + \alpha \beta \gamma $$"
        
        resp = handler.handle_process({"paper_id": 1})
        assert resp["papers_processed"] == 1
        assert resp["formulas_extracted"] == 1
        
        from shared.db import get_connection
        conn = get_connection(db_path)
        p_row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert p_row["stage"] == "extracted"
        conn.close()

    def test_handle_process_paper_not_found(self, initialized_db):
        handler = ExtractorHandler.__new__(ExtractorHandler)
        handler.db_path = str(initialized_db)
        resp = handler.handle_process({"paper_id": 999})
        assert resp["papers_processed"] == 0

    @patch("services.extractor.main.rag_client.check_service")
    def test_handle_process_service_down(self, mock_check, analyzed_paper_db):
        db_path = str(analyzed_paper_db)
        handler = ExtractorHandler.__new__(ExtractorHandler)
        handler.db_path = db_path
        # Mock send_error_json since handle_process calls it on error
        handler.send_error_json = MagicMock()
        
        mock_check.side_effect = Exception("Service Down")
        
        resp = handler.handle_process({})
        assert resp is None
        handler.send_error_json.assert_called_once()
