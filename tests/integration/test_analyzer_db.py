"""Integration tests for Analyzer service — real SQLite DB, mock LLM only."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from shared.db import transaction
from services.analyzer.main import (
    AnalyzerHandler,
    migrate_db,
)
from services.analyzer.prompt import PROMPT_VERSION
from services.discovery.main import upsert_paper
from shared.server import BaseService


# ---------------------------------------------------------------------------
# TestMigrateDbIntegration
# ---------------------------------------------------------------------------


class TestMigrateDbIntegration:
    """Integration tests for migrate_db() with real SQLite."""

    def test_migrate_real_db(self, initialized_db):
        migrate_db(str(initialized_db))

        with transaction(str(initialized_db)) as conn:
            cursor = conn.execute("PRAGMA table_info(papers)")
            columns = {row[1] for row in cursor.fetchall()}
        assert "prompt_version" in columns

    def test_migrate_preserves_data(self, initialized_db, sample_paper_row):
        # Insert paper before migration
        paper_id = upsert_paper(str(initialized_db), sample_paper_row)
        assert paper_id is not None

        migrate_db(str(initialized_db))

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["title"] == sample_paper_row["title"]
        assert row["arxiv_id"] == sample_paper_row["arxiv_id"]

    def test_prompt_version_stored_after_analyze(self, discovered_paper_db,
                                                  sample_llm_response_json):
        db_path = str(discovered_paper_db)

        with patch("services.analyzer.main.fallback_chain") as mock_fc:
            mock_fc.return_value = (sample_llm_response_json, "ollama")

            from services.analyzer.main import AnalyzerHandler
            from unittest.mock import MagicMock

            handler = MagicMock(spec=AnalyzerHandler)
            handler.db_path = db_path
            handler.threshold = 0.7
            handler.max_papers_default = 10
            handler.send_error_json = MagicMock()

            AnalyzerHandler.handle_process(handler, {})

        with transaction(db_path) as conn:
            row = conn.execute("SELECT prompt_version FROM papers WHERE id=1").fetchone()
        assert row["prompt_version"] == PROMPT_VERSION


# ---------------------------------------------------------------------------
# TestAnalyzerHandlerIntegration — real server + real DB, mock LLM
# ---------------------------------------------------------------------------


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestAnalyzerHandlerIntegration:
    """Integration tests with real HTTP server and real DB, mocked LLM."""

    @pytest.fixture(autouse=True)
    def setup_server(self, discovered_paper_db):
        self.db_path = str(discovered_paper_db)
        self.port = _get_free_port()

        AnalyzerHandler.threshold = 0.7
        AnalyzerHandler.max_papers_default = 10

        service = BaseService(
            "analyzer-test", self.port, AnalyzerHandler, db_path=self.db_path
        )
        self.thread = threading.Thread(target=service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        self.service = service
        yield
        if service.server:
            service.server.shutdown()

    def _post(self, path, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())

    def _post_error(self, path, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        return exc_info.value.code, json.loads(exc_info.value.read())

    @patch("services.analyzer.main.fallback_chain")
    def test_analyze_single_paper(self, mock_fc, sample_llm_response_json):
        mock_fc.return_value = (sample_llm_response_json, "ollama")

        result = self._post("/process", {})
        assert result["papers_analyzed"] == 1
        assert result["papers_accepted"] == 1
        assert result["papers_rejected"] == 0
        assert result["llm_provider"] == "ollama"
        assert result["prompt_version"] == "v2"

        # Verify DB state
        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "analyzed"
        assert row["score"] > 0

    @patch("services.analyzer.main.fallback_chain")
    def test_reject_low_score(self, mock_fc, sample_low_score_response):
        mock_fc.return_value = (sample_low_score_response, "ollama")

        result = self._post("/process", {})
        assert result["papers_analyzed"] == 1
        assert result["papers_accepted"] == 0
        assert result["papers_rejected"] == 1

        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "rejected"

    @patch("services.analyzer.main.fallback_chain")
    def test_threshold_boundary_exact(self, mock_fc):
        """Score exactly 0.7 → accepted (>= threshold)."""
        scores = {
            "scores": {
                "topic_relevance": 0.7,
                "mathematical_rigor": 0.7,
                "novelty": 0.7,
                "practical_applicability": 0.7,
                "data_quality": 0.7,
            },
            "reasoning": "Boundary test.",
        }
        mock_fc.return_value = (json.dumps(scores), "ollama")

        result = self._post("/process", {})
        assert result["papers_accepted"] == 1

        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "analyzed"

    @patch("services.analyzer.main.fallback_chain")
    def test_threshold_boundary_below(self, mock_fc):
        """Score just below 0.7 → rejected."""
        scores = {
            "scores": {
                "topic_relevance": 0.69,
                "mathematical_rigor": 0.69,
                "novelty": 0.69,
                "practical_applicability": 0.69,
                "data_quality": 0.69,
            },
            "reasoning": "Below threshold.",
        }
        mock_fc.return_value = (json.dumps(scores), "ollama")

        result = self._post("/process", {})
        assert result["papers_rejected"] == 1

        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "rejected"

    @patch("services.analyzer.main.fallback_chain")
    def test_force_reprocess(self, mock_fc, sample_llm_response_json):
        mock_fc.return_value = (sample_llm_response_json, "ollama")

        # First run: analyze paper
        self._post("/process", {})
        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "analyzed"

        # Without force: no papers to process
        result = self._post("/process", {})
        assert result["papers_analyzed"] == 0

        # With force + paper_id: reprocess
        result = self._post("/process", {"paper_id": 1, "force": True})
        assert result["papers_analyzed"] == 1

    @patch("services.analyzer.main.fallback_chain")
    def test_specific_paper_id(self, mock_fc, sample_llm_response_json):
        # Add a second paper
        upsert_paper(self.db_path, {
            "arxiv_id": "2401.00002",
            "title": "Second Paper",
            "abstract": "Second abstract with enough characters for testing.",
            "authors": '["C"]',
            "categories": '["stat.ML"]',
            "doi": None,
            "pdf_url": None,
            "published_date": "2024-01-16",
            "stage": "discovered",
        })

        mock_fc.return_value = (sample_llm_response_json, "ollama")

        # Only analyze paper 2
        result = self._post("/process", {"paper_id": 2})
        assert result["papers_analyzed"] == 1

        # Paper 1 should still be discovered
        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "discovered"

    @patch("services.analyzer.main.fallback_chain")
    def test_batch_mixed_results(self, mock_fc):
        # Add more papers
        for i in range(2):
            upsert_paper(self.db_path, {
                "arxiv_id": f"2401.0000{i+2}",
                "title": f"Paper {i+2}",
                "abstract": f"Abstract for paper {i+2} with sufficient length for processing.",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "discovered",
            })

        # First call: high score, second: low, third: invalid JSON
        high = json.dumps({
            "scores": {"topic_relevance": 0.9, "mathematical_rigor": 0.8,
                       "novelty": 0.7, "practical_applicability": 0.8,
                       "data_quality": 0.7},
            "reasoning": "Good.",
        })
        low = json.dumps({
            "scores": {"topic_relevance": 0.1, "mathematical_rigor": 0.2,
                       "novelty": 0.1, "practical_applicability": 0.1,
                       "data_quality": 0.1},
            "reasoning": "Bad.",
        })

        mock_fc.side_effect = [
            (high, "ollama"),
            (low, "ollama"),
            RuntimeError("LLM down"),
        ]

        result = self._post("/process", {})
        assert result["papers_accepted"] == 1
        assert result["papers_rejected"] == 1
        assert len(result["errors"]) >= 1

    @patch("services.analyzer.main.fallback_chain")
    def test_all_llm_fail(self, mock_fc):
        mock_fc.side_effect = RuntimeError("All LLM providers failed")

        result = self._post("/process", {})
        assert result["papers_analyzed"] == 0
        assert len(result["errors"]) == 1

        # Paper should remain discovered
        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "discovered"


# ---------------------------------------------------------------------------
# TestScoreStorage
# ---------------------------------------------------------------------------


class TestScoreStorage:
    """Integration tests for score persistence in DB."""

    def test_score_persisted(self, discovered_paper_db, sample_llm_response_json):
        db_path = str(discovered_paper_db)

        with patch("services.analyzer.main.fallback_chain") as mock_fc:
            mock_fc.return_value = (sample_llm_response_json, "ollama")

            from unittest.mock import MagicMock
            handler = MagicMock(spec=AnalyzerHandler)
            handler.db_path = db_path
            handler.threshold = 0.7
            handler.max_papers_default = 10
            handler.send_error_json = MagicMock()
            AnalyzerHandler.handle_process(handler, {})

        with transaction(db_path) as conn:
            row = conn.execute("SELECT score FROM papers WHERE id=1").fetchone()
        # Expected: mean(0.85, 0.70, 0.60, 0.75, 0.65) = 0.71
        assert abs(row["score"] - 0.71) < 0.01

    def test_prompt_version_stored(self, discovered_paper_db, sample_llm_response_json):
        db_path = str(discovered_paper_db)

        with patch("services.analyzer.main.fallback_chain") as mock_fc:
            mock_fc.return_value = (sample_llm_response_json, "ollama")

            from unittest.mock import MagicMock
            handler = MagicMock(spec=AnalyzerHandler)
            handler.db_path = db_path
            handler.threshold = 0.7
            handler.max_papers_default = 10
            handler.send_error_json = MagicMock()
            AnalyzerHandler.handle_process(handler, {})

        with transaction(db_path) as conn:
            row = conn.execute(
                "SELECT prompt_version FROM papers WHERE id=1"
            ).fetchone()
        assert row["prompt_version"] == "v2"

    def test_clamped_flag_stored(self, discovered_paper_db):
        db_path = str(discovered_paper_db)
        scores = {
            "scores": {
                "topic_relevance": 1.5,
                "mathematical_rigor": 0.7,
                "novelty": 0.6,
                "practical_applicability": 0.75,
                "data_quality": 0.65,
            },
            "reasoning": "Clamped test.",
        }

        with patch("services.analyzer.main.fallback_chain") as mock_fc:
            mock_fc.return_value = (json.dumps(scores), "ollama")

            from unittest.mock import MagicMock
            handler = MagicMock(spec=AnalyzerHandler)
            handler.db_path = db_path
            handler.threshold = 0.7
            handler.max_papers_default = 10
            handler.send_error_json = MagicMock()
            AnalyzerHandler.handle_process(handler, {})

        with transaction(db_path) as conn:
            row = conn.execute("SELECT error FROM papers WHERE id=1").fetchone()
        assert row["error"] == "score_clamped"
