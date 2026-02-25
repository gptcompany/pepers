"""Unit tests for PePeRS setup wizard steps."""

from __future__ import annotations

import json
import os
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
from services.setup import main as setup_main
from services.setup._config import _CONFIG_VARS, _read_env_values, EnvConfig
from services.setup._mcp_config import McpConfigStep
from services.setup._services import _EXTERNAL_SERVICES, ExternalServiceCheck
from services.setup._verify import _EXTERNAL, AggregatedHealthCheck


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
            "RP_DB_PATH=/tmp/test.db\n"
            "RP_DISCOVERY_PORT=8770\n"
            "RP_VALIDATOR_CAS_URL=http://localhost:8769\n"
            "RP_EXTRACTOR_RAG_URL=http://localhost:8767\n"
            "RP_CODEGEN_OLLAMA_URL=http://localhost:11434\n"
        )
        step = EnvConfig(tmp_path)
        assert step.check() is True

    def test_verify_checks_file_exists(self, tmp_path):
        step = EnvConfig(tmp_path)
        assert step.verify() is False
        env_file = tmp_path / ".env"
        env_file.write_text("something")
        assert step.verify() is True

    def test_read_env_values_parses_simple_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\nRP_DB_PATH=data/research.db\nRP_LOG_LEVEL=INFO\nINVALID\n"
        )
        values = _read_env_values(env_file)
        assert values["RP_DB_PATH"] == "data/research.db"
        assert values["RP_LOG_LEVEL"] == "INFO"
        assert "INVALID" not in values

    def test_config_vars_use_service_specific_external_env_names(self):
        keys = {name for name, *_ in _CONFIG_VARS}
        assert "RP_DISCOVERY_SOURCES" in keys
        assert "RP_VALIDATOR_MAX_FORMULAS" in keys
        assert "RP_CODEGEN_MAX_FORMULAS" in keys
        assert "RP_ORCHESTRATOR_CRON" in keys
        assert "RP_ORCHESTRATOR_STAGES_PER_RUN" in keys
        assert "RP_ORCHESTRATOR_DEFAULT_QUERY" in keys
        assert "RP_MCP_FLAVOR" in keys
        assert "RP_VALIDATOR_CAS_URL" in keys
        assert "RP_EXTRACTOR_RAG_URL" in keys
        assert "RP_RAG_QUERY_URL" in keys
        assert "RP_CODEGEN_OLLAMA_URL" in keys
        assert "RP_CAS_URL" not in keys
        assert "RP_RAG_URL" not in keys
        assert "RP_OLLAMA_URL" not in keys


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

    @patch("requests.get")
    def test_check_prefers_new_env_key_over_legacy(self, mock_get):
        mock_get.return_value.status_code = 200
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        with patch.dict(
            os.environ,
            {"RP_CAS_URL": "http://legacy:1", "RP_VALIDATOR_CAS_URL": "http://new:2"},
            clear=False,
        ):
            step = ExternalServiceCheck(svc)
            assert step.check() is True
        mock_get.assert_called_once_with("http://new:2/health", timeout=5)

    def test_external_service_constants_are_aligned(self):
        by_name = {svc["name"]: svc for svc in _EXTERNAL_SERVICES}
        assert by_name["CAS Service"]["env_urls"][0] == "RP_VALIDATOR_CAS_URL"
        assert by_name["RAG Service"]["env_urls"][0] == "RP_EXTRACTOR_RAG_URL"
        assert by_name["CAS Service"]["setup_cmd"] == "cas-setup"
        assert by_name["RAG Service"]["setup_cmd"] == "rag-setup"
        assert "Ollama" not in by_name

    @patch("services.setup._services.subprocess.run")
    @patch("services.setup._services.questionary.confirm")
    @patch("services.setup._services.shutil.which", return_value="/usr/bin/cas-setup")
    def test_install_can_launch_subprocess_setup_cli(
        self,
        mock_which,
        mock_confirm,
        mock_run,
    ):
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "setup_cmd": "cas-setup",
            "setup_hint": "Install CAS",
        }
        mock_confirm.return_value.ask.return_value = True
        mock_run.return_value.returncode = 0
        step = ExternalServiceCheck(svc)
        console = MagicMock()

        result = step.install(console)

        assert result is True
        mock_confirm.assert_called_once()
        mock_run.assert_called_once_with(["cas-setup"], check=False)


# ── MCP config ───────────────────────────────────────────────

class TestMcpConfigStep:
    def test_install_writes_claude_config_and_verify_passes(self, tmp_path):
        step = McpConfigStep()
        console = MagicMock()
        config_path = tmp_path / ".claude.json"

        with patch("services.setup._mcp_config.Path.home", return_value=tmp_path):
            assert step.check() is False
            assert step.install(console) is True
            assert config_path.exists()

            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["pepers"]["type"] == "sse"
            assert data["mcpServers"]["pepers"]["url"] == "http://localhost:8776/sse"
            assert step.verify() is True

    def test_install_fails_on_invalid_existing_json(self, tmp_path):
        step = McpConfigStep()
        console = MagicMock()
        (tmp_path / ".claude.json").write_text("{not json")

        with patch("services.setup._mcp_config.Path.home", return_value=tmp_path):
            assert step.install(console) is False


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

    @patch("services.setup._verify._discover_rag_details", return_value="")
    @patch("services.setup._verify._discover_cas_details", return_value="")
    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_uses_service_specific_external_env_keys(self, mock_http, mock_cas, mock_rag):
        step = AggregatedHealthCheck()
        console = MagicMock()
        with patch.dict(
            os.environ,
            {
                "RP_VALIDATOR_CAS_URL": "http://cas.local:9991",
                "RP_EXTRACTOR_RAG_URL": "http://rag.local:9992",
                "RP_CODEGEN_OLLAMA_URL": "http://ollama.local:9993",
            },
            clear=False,
        ):
            step.install(console)

        called_urls = [call.args[0] for call in mock_http.call_args_list]
        assert "http://cas.local:9991/health" in called_urls
        assert "http://rag.local:9992/health" in called_urls
        assert "http://ollama.local:9993/" in called_urls

    def test_verify_constants_keep_legacy_fallbacks(self):
        cas_envs, _, _ = _EXTERNAL["CAS Service"]
        rag_envs, _, _ = _EXTERNAL["RAG Service"]
        ollama_envs, _, _ = _EXTERNAL["Ollama"]
        assert "RP_CAS_URL" in cas_envs
        assert "RP_RAG_URL" in rag_envs
        assert "RP_OLLAMA_URL" in ollama_envs

    @patch("services.setup._verify._discover_rag_details", return_value="")
    @patch("services.setup._verify._discover_cas_details", return_value="")
    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_uses_mcp_sse_endpoint(self, mock_http, mock_cas, mock_rag):
        step = AggregatedHealthCheck()
        console = MagicMock()
        step.install(console)

        called_urls = [call.args[0] for call in mock_http.call_args_list]
        assert "http://localhost:8776/sse" in called_urls


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

    @patch("questionary.select")
    def test_run_interactive_menu_exit_returns_false_when_pending(self, mock_select):
        from services.setup._runner import run_interactive_menu

        step = MagicMock()
        step.name = "Pending"
        step.description = "Test step"
        step.check.return_value = False

        mock_select.return_value.ask.return_value = "exit"
        console = MagicMock()

        result = run_interactive_menu([step], console)
        assert result is False


# ── CLI main() ────────────────────────────────────────────────

class TestSetupMainCli:
    @patch("services.setup.main.Console")
    def test_help_flag_returns_zero(self, mock_console_cls):
        rc = setup_main.main(["--help"])
        assert rc == 0
        console = mock_console_cls.return_value
        console.print.assert_called()

    @patch("services.setup._runner.run_interactive_menu", return_value=True)
    @patch("services.setup.main._all_steps", return_value=[])
    @patch("services.setup.main.Console")
    def test_all_command_uses_interactive_menu(
        self,
        mock_console_cls,
        mock_all_steps,
        mock_run_menu,
    ):
        rc = setup_main.main(["all"])
        assert rc == 0
        mock_all_steps.assert_called_once()
        mock_run_menu.assert_called_once()
