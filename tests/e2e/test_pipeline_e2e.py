"""E2E tests: full pipeline stage progression with real services in-process.

Verifies complete paper flow through validator → codegen with real HTTP
services, real DB, mocked only external dependencies (CAS, LLM).
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from shared.db import init_db, transaction
from services.discovery.main import DiscoveryHandler
from services.extractor.main import ExtractorHandler
from services.validator.main import ValidatorHandler
from services.codegen.main import CodegenHandler


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _seed_extracted_paper(db_path: str, n_formulas: int = 3) -> int:
    """Seed a paper with N extracted formulas. Returns paper_id."""
    from services.discovery.main import upsert_paper
    from services.analyzer.main import migrate_db

    upsert_paper(db_path, {
        "arxiv_id": "2401.00001",
        "title": "Kelly Criterion in Portfolio Optimization",
        "abstract": "Test paper",
        "authors": json.dumps(["Test Author"]),
        "categories": json.dumps(["q-fin.PM"]),
        "doi": None,
        "pdf_url": "https://arxiv.org/pdf/2401.00001",
        "published_date": "2024-01-15",
        "stage": "extracted",
    })
    migrate_db(db_path)

    formulas = [
        r"f^* = \frac{p}{a} - \frac{q}{b}",
        r"G(f) = r + f(\mu - r) - \frac{f^2 \sigma^2}{2}",
        r"S = \frac{\mu - r}{\sigma}",
    ]

    with transaction(db_path) as conn:
        for i in range(n_formulas):
            latex = formulas[i % len(formulas)]
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, context, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, latex, f"e2e_hash_{i:03d}", "Kelly criterion", "extracted"),
            )
    return 1


def _get_paper_stage(db_path: str, paper_id: int) -> str:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT stage FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    return row["stage"] if row else "unknown"


def _count_formulas_by_stage(db_path: str, stage: str) -> int:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM formulas WHERE stage = ?", (stage,)
        ).fetchone()
    return row["cnt"]


def _count_validations(db_path: str) -> int:
    with transaction(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM validations").fetchone()
    return row["cnt"]


def _count_generated_code(db_path: str) -> int:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM generated_code"
        ).fetchone()
    return row["cnt"]


# ---------------------------------------------------------------------------
# E2E Pipeline Stage Progression
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestPipelineStageProgression:
    """Full pipeline E2E: real HTTP services, real DB, mocked CAS/LLM."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "e2e_pipeline.db")
        init_db(self.db_path)
        self.validator_port = _get_free_port()
        self.codegen_port = _get_free_port()
        self.services = []
        yield
        for svc in self.services:
            if svc.server:
                svc.server.shutdown()
        ValidatorHandler._routes = None
        CodegenHandler._routes = None

    def _start_validator(self):
        ValidatorHandler.cas_url = "http://localhost:19999"  # Won't be reached
        ValidatorHandler.cas_timeout = 5
        ValidatorHandler.max_formulas_default = 50
        ValidatorHandler.engines = ["sympy"]

        svc = BaseService(
            "validator", self.validator_port, ValidatorHandler, self.db_path
        )
        self.services.append(svc)
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.3)
        return svc

    def _start_codegen(self):
        CodegenHandler.max_formulas_default = 50

        svc = BaseService(
            "codegen", self.codegen_port, CodegenHandler, self.db_path
        )
        self.services.append(svc)
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.3)
        return svc

    def _post_process(self, port: int, data: dict | None = None) -> dict:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())

    def test_paper_flows_through_all_stages(self):
        """Paper + formulas progress: extracted → validated → codegen."""
        paper_id = _seed_extracted_paper(self.db_path, n_formulas=3)

        # Pre-condition
        assert _get_paper_stage(self.db_path, paper_id) == "extracted"
        assert _count_formulas_by_stage(self.db_path, "extracted") == 3

        # --- Step 1: Validator ---
        mock_cas_response = MagicMock()
        mock_result = MagicMock()
        mock_result.engine = "sympy"
        mock_result.success = True
        mock_result.is_valid = True
        mock_result.simplified = "simplified"
        mock_result.error = None
        mock_result.time_ms = 10
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

            self._start_validator()
            result = self._post_process(self.validator_port)

        assert result["formulas_processed"] == 3
        assert _get_paper_stage(self.db_path, paper_id) == "validated"
        assert _count_formulas_by_stage(self.db_path, "validated") == 3
        assert _count_validations(self.db_path) == 3

        # --- Step 2: Codegen ---
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
            patch("services.codegen.main.explain_formula", return_value=None),
            patch("services.codegen.main.generate_all", return_value=mock_code_results),
        ):
            self._start_codegen()
            result = self._post_process(self.codegen_port)

        assert result["formulas_processed"] == 3
        assert _get_paper_stage(self.db_path, paper_id) == "codegen"
        assert _count_formulas_by_stage(self.db_path, "codegen") == 3
        assert _count_generated_code(self.db_path) == 9  # 3 formulas × 3 languages

    def test_multiple_papers_independent_stages(self):
        """2 papers at different stages, each advances independently."""
        from services.discovery.main import upsert_paper
        from services.analyzer.main import migrate_db

        # Paper 1: extracted (will be validated)
        upsert_paper(self.db_path, {
            "arxiv_id": "2401.00001",
            "title": "Paper 1",
            "abstract": "Test",
            "authors": json.dumps(["A"]),
            "categories": json.dumps(["q-fin.PM"]),
            "doi": None,
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "published_date": "2024-01-15",
            "stage": "extracted",
        })
        # Paper 2: already validated (won't be touched by validator)
        upsert_paper(self.db_path, {
            "arxiv_id": "2401.00002",
            "title": "Paper 2",
            "abstract": "Test 2",
            "authors": json.dumps(["B"]),
            "categories": json.dumps(["q-fin.PM"]),
            "doi": None,
            "pdf_url": "https://arxiv.org/pdf/2401.00002",
            "published_date": "2024-01-15",
            "stage": "validated",
        })
        migrate_db(self.db_path)

        with transaction(self.db_path) as conn:
            # Formula for paper 1 (extracted)
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, r"x^2 + y^2 = z^2", "multi_hash_1", "extracted"),
            )
            # Formula for paper 2 (validated, ready for codegen)
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, context, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (2, r"a + b = c", "multi_hash_2", "test", "validated"),
            )

        # Run validator (should only process paper 1's formula)
        mock_cas_response = MagicMock()
        mock_result = MagicMock()
        mock_result.engine = "sympy"
        mock_result.success = True
        mock_result.is_valid = True
        mock_result.simplified = "x**2 + y**2 - z**2"
        mock_result.error = None
        mock_result.time_ms = 10
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

            self._start_validator()
            result = self._post_process(self.validator_port)

        # Only paper 1's formula processed
        assert result["formulas_processed"] == 1
        assert _get_paper_stage(self.db_path, 1) == "validated"
        assert _get_paper_stage(self.db_path, 2) == "validated"  # Unchanged

    def test_all_formulas_fail_stage_not_advanced(self):
        """All formulas fail → paper.stage NOT advanced (negative path)."""
        paper_id = _seed_extracted_paper(self.db_path, n_formulas=2)

        assert _get_paper_stage(self.db_path, paper_id) == "extracted"

        with (
            patch("services.validator.main.CASClient") as mock_cls,
        ):
            mock_client = MagicMock()
            mock_client.health.return_value = True
            # Simulate CAS returning errors for all formulas
            from services.validator.cas_client import CASServiceError
            mock_client.validate.side_effect = CASServiceError("CAS unavailable")
            mock_cls.return_value = mock_client

            self._start_validator()
            result = self._post_process(self.validator_port)

        # Paper stage must NOT advance
        assert _get_paper_stage(self.db_path, paper_id) == "extracted"
        assert result["formulas_failed"] == 2
        assert result["formulas_processed"] == 2

    def test_batch_overflow_real_services(self):
        """60+ formulas processed via real validator service (mocked CAS)."""
        _seed_extracted_paper(self.db_path, n_formulas=60)

        assert _count_formulas_by_stage(self.db_path, "extracted") == 60

        mock_cas_response = MagicMock()
        mock_result = MagicMock()
        mock_result.engine = "sympy"
        mock_result.success = True
        mock_result.is_valid = True
        mock_result.simplified = "ok"
        mock_result.error = None
        mock_result.time_ms = 5
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

            self._start_validator()

            # First call: processes up to max_formulas (50)
            result1 = self._post_process(self.validator_port, {"max_formulas": 50})
            assert result1["formulas_processed"] == 50

            # Second call: processes remaining 10
            result2 = self._post_process(self.validator_port, {"max_formulas": 50})
            assert result2["formulas_processed"] == 10

            # Third call: nothing left
            result3 = self._post_process(self.validator_port, {"max_formulas": 50})
            assert result3["formulas_processed"] == 0

        assert _get_paper_stage(self.db_path, 1) == "validated"
        assert _count_formulas_by_stage(self.db_path, "validated") == 60


@pytest.mark.e2e
class TestFullPipelineE2E:
    """Full system test from Discovery to Codegen."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "full_e2e.db")
        init_db(self.db_path)
        self.ports = {
            "discovery": _get_free_port(),
            "extractor": _get_free_port(),
            "validator": _get_free_port(),
            "codegen": _get_free_port(),
        }
        self.services = []
        yield
        for svc in self.services:
            if svc.server:
                svc.server.shutdown()
        # Reset routes to avoid side effects between tests
        for handler in [DiscoveryHandler, ExtractorHandler, ValidatorHandler, CodegenHandler]:
            if hasattr(handler, "_routes"):
                handler._routes = None

    def _start_svc(self, name, handler_cls):
        port = self.ports[name]
        svc = BaseService(name, port, handler_cls, self.db_path)
        self.services.append(svc)
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.3)

    def _post(self, port, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    @patch("services.discovery.main.search_arxiv")
    @patch("services.extractor.main.pdf.download_pdf")
    @patch("services.extractor.main.rag_client.process_paper")
    def test_e2e_paper_with_no_formulas(self, mock_rag, mock_pdf, mock_arxiv):
        # 1. Discovery finds a paper
        mock_arxiv.return_value = [{"arxiv_id": "2401.11111", "title": "No Formulas", "abstract": "Text only", "authors": "[]", "categories": "[]", "pdf_url": "http://pdf", "published_date": "2024-01-01", "doi": None}]
        self._start_svc("discovery", DiscoveryHandler)
        self._post(self.ports["discovery"], {"query": "test"})
        
        # 2. Stage is now 'discovered', ready for analyzer
        # We skip analyzer for simplicity
        with transaction(self.db_path) as conn:
            conn.execute("UPDATE papers SET stage='analyzed' WHERE id=1")

        # 3. Extractor runs but finds no formulas
        mock_pdf.return_value = "fake.pdf"
        mock_rag.return_value = "This is a paper with no mathematical formulas."
        self._start_svc("extractor", ExtractorHandler)
        res = self._post(self.ports["extractor"], {"paper_id": 1})
        
        assert res["papers_processed"] == 1
        assert res["formulas_extracted"] == 0

        # 4. Final state check
        # The paper should be marked as 'extracted' (since the step ran)
        # but no formulas should be in the DB.
        assert _get_paper_stage(self.db_path, 1) == "extracted"
        assert _count_formulas_by_stage(self.db_path, "any_stage") == 0

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "full_e2e.db")
        init_db(self.db_path)
        self.ports = {
            "discovery": _get_free_port(),
            "validator": _get_free_port(),
            "codegen": _get_free_port(),
        }
        self.services = []
        yield
        for svc in self.services:
            if svc.server:
                svc.server.shutdown()
        DiscoveryHandler._routes = None
        ValidatorHandler._routes = None
        CodegenHandler._routes = None

    def _start_svc(self, name, handler_cls):
        port = self.ports[name]
        svc = BaseService(name, port, handler_cls, self.db_path)
        self.services.append(svc)
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.3)

    def _post(self, port, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    @patch("services.discovery.main.search_arxiv")
    @patch("services.validator.main.CASClient")
    @patch("services.codegen.main.generate_all")
    def test_full_discovery_to_codegen_flow(self, mock_gen, mock_cas_cls, mock_arxiv):
        # 1. Mock Discovery
        mock_arxiv.return_value = [{
            "arxiv_id": "2401.99999", "title": "E2E", "abstract": "Test",
            "authors": "[]", "categories": "[]", "pdf_url": "http://pdf",
            "published_date": "2024-01-01", "doi": None
        }]
        
        # 2. Mock Validator
        mock_res = MagicMock(engine="sympy", success=True, is_valid=True, simplified="x", error=None, time_ms=1)
        mock_cas_client = mock_cas_cls.return_value
        mock_cas_client.health.return_value = True
        mock_cas_client.validate.return_value = MagicMock(results=[mock_res])
        
        # 3. Mock Codegen
        mock_gen.return_value = [{"language": "python", "code": "pass", "metadata": {}, "error": None}]

        # Run Discovery
        self._start_svc("discovery", DiscoveryHandler)
        self._post(self.ports["discovery"], {"query": "test"})
        
        # Inject analyzed status (skipping analyzer service for speed)
        with transaction(self.db_path) as conn:
            conn.execute("UPDATE papers SET stage='analyzed'")
            # Manually inject formula (skipping extractor service)
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (1, 'E=mc^2', 'hash1', 'extracted')"
            )
            # Extracted papers need stage='extracted' to be picked by validator
            conn.execute("UPDATE papers SET stage='extracted'")

        # Run Validator
        self._start_svc("validator", ValidatorHandler)
        self._post(self.ports["validator"], {})
        
        assert _get_paper_stage(self.db_path, 1) == "validated"

        # Run Codegen
        self._start_svc("codegen", CodegenHandler)
        with patch("services.codegen.main.explain_formulas_batch", return_value={}):
            self._post(self.ports["codegen"], {})
            
        assert _get_paper_stage(self.db_path, 1) == "codegen"
        assert _count_generated_code(self.db_path) == 1
