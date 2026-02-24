"""Unit tests for PePeRS setup wizard steps."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

from services.setup._checks import (
    DiskSpaceCheck,
    DotenvxCheck,
    PythonCheck,
    SQLiteCheck,
    UvCheck,
    VenvCheck,
)
from services.setup._config import EnvConfig
from services.setup._services import ExternalServiceCheck
from services.setup._verify import AggregatedHealthCheck


# ── PythonCheck ──────────────────────────────────────────────

class TestPythonCheck:
    def test_check_passes_on_current_python(self):
        step = PythonCheck()
        # We're running >= 3.10
        assert step.check() is True

    def test_verify_same_as_check(self):
        step = PythonCheck()
        assert step.verify() == step.check()

    def test_install_returns_false(self):
        """Python can't be auto-installed."""
        step = PythonCheck()
        console = MagicMock()
        assert step.install(console) is False


# ── UvCheck ──────────────────────────────────────────────────

class TestUvCheck:
    @patch("shutil.which", return_value="/usr/bin/uv")
    def test_check_passes_when_uv_found(self, mock_which):
        step = UvCheck()
        assert step.check() is True

    @patch("shutil.which", return_value=None)
    def test_check_fails_when_uv_missing(self, mock_which):
        step = UvCheck()
        assert step.check() is False

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_install_fails_gracefully(self, mock_run, mock_which):
        step = UvCheck()
        console = MagicMock()
        assert step.install(console) is False


# ── SQLiteCheck ──────────────────────────────────────────────

class TestSQLiteCheck:
    def test_check_passes_on_modern_sqlite(self):
        step = SQLiteCheck()
        # Python bundles SQLite >= 3.35 on modern systems
        version = sqlite3.sqlite_version_info
        expected = version >= (3, 35, 0)
        assert step.check() == expected


# ── VenvCheck ────────────────────────────────────────────────

class TestVenvCheck:
    def test_check_passes_when_venv_exists(self, tmp_path):
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()
        step = VenvCheck(tmp_path)
        assert step.check() is True

    def test_check_fails_when_no_venv(self, tmp_path):
        step = VenvCheck(tmp_path)
        assert step.check() is False


# ── DotenvxCheck ─────────────────────────────────────────────

class TestDotenvxCheck:
    @patch("shutil.which", return_value="/usr/bin/dotenvx")
    def test_check_passes(self, mock_which):
        step = DotenvxCheck()
        assert step.check() is True

    @patch("shutil.which", return_value=None)
    def test_check_fails(self, mock_which):
        step = DotenvxCheck()
        assert step.check() is False


# ── DiskSpaceCheck ───────────────────────────────────────────

class TestDiskSpaceCheck:
    def test_check_passes_on_normal_system(self, tmp_path):
        step = DiskSpaceCheck(tmp_path)
        # Should have > 500MB free on any test system
        assert step.check() is True


# ── EnvConfig ────────────────────────────────────────────────

class TestEnvConfig:
    def test_check_fails_when_no_env(self, tmp_path):
        step = EnvConfig(tmp_path)
        assert step.check() is False

    def test_check_passes_with_valid_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "RP_DB_PATH=/tmp/test.db\nRP_DISCOVERY_PORT=8770\n"
        )
        step = EnvConfig(tmp_path)
        assert step.check() is True

    def test_verify_checks_file_exists(self, tmp_path):
        step = EnvConfig(tmp_path)
        assert step.verify() is False
        env_file = tmp_path / ".env"
        env_file.write_text("something")
        assert step.verify() is True


# ── ExternalServiceCheck ─────────────────────────────────────

class TestExternalServiceCheck:
    @patch("requests.get", side_effect=__import__("requests").ConnectionError("refused"))
    def test_check_fails_on_unreachable_service(self, mock_get):
        svc = {
            "name": "Test Service",
            "env_url": "TEST_URL",
            "default_url": "http://localhost:19999",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        step = ExternalServiceCheck(svc)
        assert step.check() is False

    def test_install_shows_hint(self):
        svc = {
            "name": "Test Service",
            "env_url": "TEST_URL",
            "default_url": "http://localhost:19999",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        step = ExternalServiceCheck(svc)
        console = MagicMock()
        result = step.install(console)
        assert result is False
        console.print.assert_called()  # showed hint


# ── AggregatedHealthCheck ────────────────────────────────────

class TestAggregatedHealthCheck:
    def test_check_always_false(self):
        """Aggregated check always runs full verification."""
        step = AggregatedHealthCheck()
        assert step.check() is False

    def test_install_returns_true(self):
        """Install is informational, always succeeds."""
        step = AggregatedHealthCheck()
        console = MagicMock()
        assert step.install(console) is True

    def test_verify_always_true(self):
        step = AggregatedHealthCheck()
        assert step.verify() is True

    @patch("services.setup._verify._discover_rag_details", return_value="")
    @patch("services.setup._verify._discover_cas_details",
           return_value="sympy, maxima, gap (3 eng.)")
    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_shows_cas_details_when_up(self, mock_http, mock_cas, mock_rag):
        """When CAS is up, details column shows discovered engines."""
        step = AggregatedHealthCheck()
        console = MagicMock()
        step.install(console)
        # Table was printed to console
        console.print.assert_called()
        mock_cas.assert_called_once()

    @patch("services.setup._verify._discover_rag_details",
           return_value="queue: 0/12, CB: closed")
    @patch("services.setup._verify._discover_cas_details", return_value="")
    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_shows_rag_details_when_up(self, mock_http, mock_cas, mock_rag):
        """When RAG is up, details column shows queue/CB info."""
        step = AggregatedHealthCheck()
        console = MagicMock()
        step.install(console)
        console.print.assert_called()
        mock_rag.assert_called_once()

    @patch("services.setup._verify._discover_cas_details")
    @patch("services.setup._verify._check_http", return_value=False)
    def test_install_skips_discovery_when_down(self, mock_http, mock_cas):
        """When service is down, skip capability discovery."""
        step = AggregatedHealthCheck()
        console = MagicMock()
        step.install(console)
        mock_cas.assert_not_called()


# ── Runner ───────────────────────────────────────────────────

class TestRunner:
    @patch("questionary.confirm")
    def test_run_steps_skips_passing_checks(self, mock_confirm):
        from services.setup._runner import run_steps

        step = MagicMock()
        step.name = "Test"
        step.check.return_value = True

        console = MagicMock()
        console.status.return_value.__enter__ = MagicMock()
        console.status.return_value.__exit__ = MagicMock()

        result = run_steps([step], console)
        assert result is True
        step.install.assert_not_called()
        mock_confirm.assert_not_called()

    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_run_steps_abort_on_failure(self, mock_select, mock_confirm):
        from services.setup._runner import run_steps

        step = MagicMock()
        step.name = "Failing"
        step.check.return_value = False
        step.install.return_value = False

        mock_confirm.return_value.ask.return_value = True
        mock_select.return_value.ask.return_value = "Abort"

        console = MagicMock()
        console.status.return_value.__enter__ = MagicMock()
        console.status.return_value.__exit__ = MagicMock()

        result = run_steps([step], console)
        assert result is False

    @patch("questionary.confirm")
    def test_run_steps_user_skips(self, mock_confirm):
        from services.setup._runner import run_steps

        step = MagicMock()
        step.name = "Optional"
        step.check.return_value = False

        mock_confirm.return_value.ask.return_value = False  # user says no

        console = MagicMock()
        console.status.return_value.__enter__ = MagicMock()
        console.status.return_value.__exit__ = MagicMock()

        result = run_steps([step], console)
        assert result is True
        step.install.assert_not_called()
