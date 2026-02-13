"""Unit tests for the Extractor service — all external calls mocked."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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
    extract_context,
    extract_formulas,
    filter_formulas,
    formulas_to_models,
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
        assert adapter.max_retries.total == 3


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

        # Pass container path
        container_path = str(host_dir).replace("/media/sam/1TB/", "/workspace/1TB/")
        # read_markdown maps /workspace/1TB/ → /media/sam/1TB/
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
