"""Unit tests for PePeRS setup wizard steps."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from unittest.mock import MagicMock, patch

from services.setup._checks import (
    DiskSpaceCheck,
    DotenvxCheck,
    PythonCheck,
    SQLiteCheck,
    UvCheck,
    VenvCheck,
)
from services.setup._cli_tools import NodeCheck, NpmCliTool, OllamaCheck
from services.setup._docker import (
    DockerCheck,
    DockerComposeCheck,
    DockerComposeUp,
)
from services.setup import main as setup_main
from services.setup._config import (
    _CONFIG_VARS,
    _read_env_values,
    _validate_port,
    _validate_url,
    EnvConfig,
)
from services.setup._mcp_config import McpConfigStep
from services.setup._services import (
    _EXTERNAL_SERVICES,
    ExternalServiceCheck,
    ExternalServicePersistenceCheck,
    get_all_steps as get_services_steps,
)
from services.setup._verify import _EXTERNAL, AggregatedHealthCheck


# ── PythonCheck ──────────────────────────────────────────────

class TestPythonCheck:
    def test_check_passes_on_current_python(self):
        step = PythonCheck()
        # We're running >= 3.10
        assert step.check() is True

    def test_check_fails_on_old_python(self):
        step = PythonCheck()
        with patch("services.setup._checks.sys.version_info", (3, 8, 0)):
            assert step.check() is False

    def test_verify_same_as_check(self):
        step = PythonCheck()
        assert step.verify() == step.check()

    def test_install_fails(self):
        step = PythonCheck()
        assert step.install(MagicMock()) is False


class TestDiskSpaceCheck:
    def test_check_passes_on_normal_system(self, tmp_path):
        step = DiskSpaceCheck(tmp_path)
        assert step.check() is True

    def test_check_with_data_dir(self, tmp_path):
        (tmp_path / "data").mkdir()
        step = DiskSpaceCheck(tmp_path)
        assert step.check() is True

    @patch("shutil.disk_usage")
    def test_check_fails_on_low_space(self, mock_usage, tmp_path):
        # 5MB free (less than 500MB required)
        mock_usage.return_value = MagicMock(total=500*1024*1024, free=5*1024*1024)
        step = DiskSpaceCheck(tmp_path)
        assert step.check() is False

    @patch("shutil.disk_usage")
    def test_install_prints_space_warning(self, mock_usage, tmp_path):
        mock_usage.return_value = MagicMock(total=500*1024*1024, free=5*1024*1024)
        step = DiskSpaceCheck(tmp_path)
        console = MagicMock()
        assert step.install(console) is False
        console.print.assert_called()

    def test_verify_calls_check(self, tmp_path):
        step = DiskSpaceCheck(tmp_path)
        assert step.verify() == step.check()

class TestNodeCheck:
    @patch("shutil.which", return_value="/usr/bin/node")
    @patch("subprocess.run")
    def test_check_passes_node18(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(stdout="v18.15.0\n")
        step = NodeCheck()
        assert step.check() is True

    @patch("shutil.which", return_value="/usr/bin/node")
    @patch("subprocess.run")
    def test_check_fails_old_node(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(stdout="v16.0.0\n")
        step = NodeCheck()
        assert step.check() is False

    @patch("platform.system", return_value="Linux")
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "curl"))
    def test_install_linux_fails(self, mock_run, mock_platform):
        console = MagicMock()
        step = NodeCheck()
        assert step.install(console) is False

    @patch("shutil.which", return_value=None)
    def test_npm_tool_install_fails_no_npm(self, mock_which):
        step = NpmCliTool("T", "D", "b", "p")
        assert step.install(MagicMock()) is False

    @patch("shutil.which", return_value="/usr/bin/npm")
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "npm"))
    def test_npm_tool_install_fails_subprocess(self, mock_run, mock_which):
        step = NpmCliTool("T", "D", "b", "p")
        assert step.install(MagicMock()) is False

    @patch("platform.system", return_value="Darwin")
    @patch("services.setup._cli_tools._ensure_macports", return_value=True)
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "port"))
    def test_install_macos_fails(self, mock_run, mock_ensure, mock_platform):
        console = MagicMock()
        step = NodeCheck()
        assert step.install(console) is False

    @patch("platform.system", return_value="Windows")
    def test_install_windows_unsupported(self, mock_platform):
        console = MagicMock()
        step = NodeCheck()
        assert step.install(console) is False


# ── OllamaCheck ──────────────────────────────────────────────

class TestOllamaCheck:
    @patch("shutil.which", return_value="/usr/bin/ollama")
    def test_check_passes(self, mock_which):
        step = OllamaCheck()
        assert step.check() is True

    @patch("platform.system", return_value="Darwin")
    @patch("services.setup._cli_tools._ensure_macports", return_value=True)
    @patch("subprocess.run")
    def test_install_macos(self, mock_run, mock_ensure, mock_platform):
        console = MagicMock()
        step = OllamaCheck()
        mock_run.return_value = MagicMock(returncode=0)
        assert step.install(console) is True
        mock_run.assert_called_with(
            ["sudo", "port", "install", "ollama"], check=True, text=True,
        )

    @patch("platform.system", return_value="Linux")
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "sh"))
    def test_install_fails_subprocess_error(self, mock_run, mock_platform):
        step = OllamaCheck()
        console = MagicMock()
        assert step.install(console) is False

    @patch("shutil.which", return_value="/usr/bin/ollama")
    def test_verify_calls_check(self, mock_which):
        step = OllamaCheck()
        assert step.verify() == step.check()


# ── NpmCliTool ───────────────────────────────────────────────

class TestNpmCliTool:
    @patch("platform.system", return_value="Linux")
    @patch("shutil.which")
    @patch("subprocess.run")
    def test_install_success_linux(self, mock_run, mock_which, mock_platform):
        mock_which.side_effect = lambda x: "/usr/bin/npm" if x == "npm" else None
        mock_run.return_value = MagicMock(returncode=0)

        step = NpmCliTool("Test", "Desc", "test-bin", "test-pkg")
        console = MagicMock()
        assert step.install(console) is True
        mock_run.assert_called_with(
            ["npm", "install", "-g", "test-pkg"],
            check=True, capture_output=True, text=True,
        )

    @patch("platform.system", return_value="Darwin")
    @patch("shutil.which")
    @patch("subprocess.run")
    def test_install_success_macos_uses_sudo(self, mock_run, mock_which, mock_platform):
        mock_which.side_effect = lambda x: "/usr/bin/npm" if x == "npm" else ("/usr/bin/port" if x == "port" else None)
        mock_run.return_value = MagicMock(returncode=0)

        step = NpmCliTool("Test", "Desc", "test-bin", "test-pkg")
        console = MagicMock()
        assert step.install(console) is True
        mock_run.assert_called_with(
            ["sudo", "npm", "install", "-g", "test-pkg"],
            check=True, capture_output=True, text=True,
        )

    @patch("shutil.which", return_value=None)
    def test_install_fails_no_npm(self, mock_which):
        step = NpmCliTool("Test", "Desc", "test-bin", "test-pkg")
        console = MagicMock()
        assert step.install(console) is False

    @patch("shutil.which", return_value="/usr/bin/npm")
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "npm"))
    def test_install_fails_npm_error(self, mock_run, mock_which):
        step = NpmCliTool("Test", "Desc", "test-bin", "test-pkg")
        console = MagicMock()
        assert step.install(console) is False


# ── DockerCheck ──────────────────────────────────────────────

class TestDockerCheck:
    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_check_passes(self, mock_which):
        step = DockerCheck()
        assert step.check() is True

    def test_install_unsupported(self):
        step = DockerCheck()
        assert step.install(MagicMock()) is False


# ── DockerComposeCheck ───────────────────────────────────────

class TestDockerComposeCheck:
    @patch("subprocess.run")
    def test_check_passes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        step = DockerComposeCheck()
        assert step.check() is True

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_check_fails_missing(self, mock_run):
        step = DockerComposeCheck()
        assert step.check() is False

    def test_install_unsupported(self):
        step = DockerComposeCheck()
        assert step.install(MagicMock()) is False


# ── DockerComposeUp ──────────────────────────────────────────

    def test_compose_file_missing(self, tmp_path):
        step = DockerComposeUp(tmp_path)
        assert step._compose_file() is None
        # Implementation returns True for check/install/verify if no file
        assert step.check() is True
        assert step.install(MagicMock()) is True
        assert step.verify() is True

    @patch("subprocess.run")
    def test_check_passes_running(self, mock_run, tmp_path):
        (tmp_path / "compose.yml").touch()
        mock_run.return_value = MagicMock(returncode=0, stdout='{"Status": "running"}')
        step = DockerComposeUp(tmp_path)
        assert step.check() is True

    @patch("subprocess.run")
    def test_check_fails_not_running(self, mock_run, tmp_path):
        (tmp_path / "compose.yml").touch()
        # implementation: return len(result.stdout.strip()) > 0
        mock_run.return_value = MagicMock(returncode=0, stdout='') 
        step = DockerComposeUp(tmp_path)
        assert step.check() is False

    @patch("subprocess.run")
    def test_install_up(self, mock_run, tmp_path):
        (tmp_path / "compose.yml").touch()
        mock_run.return_value = MagicMock(returncode=0)
        step = DockerComposeUp(tmp_path)
        console = MagicMock()
        assert step.install(console) is True
        args, kwargs = mock_run.call_args
        assert args[0][1:4] == ["compose", "up", "-d"]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["check"] is True
        assert kwargs["text"] is True
        assert "env" in kwargs

    @patch.object(DockerComposeUp, "_retry_after_port_conflict", return_value=True)
    @patch("services.setup._docker._docker_daemon_ready", return_value=True)
    @patch("services.setup._docker._docker_bin", return_value="/usr/bin/docker")
    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker"))
    def test_install_retries_after_port_conflict(
        self,
        mock_run,
        _mock_docker_bin,
        _mock_daemon_ready,
        mock_retry,
        tmp_path,
    ):
        (tmp_path / "compose.yml").touch()
        step = DockerComposeUp(tmp_path)
        assert step.install(MagicMock()) is True
        mock_retry.assert_called_once()

    @patch("services.setup._docker.subprocess.run")
    @patch.object(EnvConfig, "_auto_resolve_internal_port_conflicts", side_effect=[True, True])
    def test_retry_after_port_conflict_can_retry_multiple_times(
        self,
        _mock_remap,
        mock_run,
        tmp_path,
    ):
        env_path = tmp_path / ".env"
        env_path.write_text("RP_MCP_PORT=8776\n")
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "docker"),
            MagicMock(returncode=0),
        ]
        step = DockerComposeUp(tmp_path)

        assert step._retry_after_port_conflict(MagicMock(), "/usr/bin/docker") is True
        assert mock_run.call_count == 2

    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker"))
    def test_install_fails_on_error(self, mock_run, tmp_path):
        (tmp_path / "compose.yml").touch()
        step = DockerComposeUp(tmp_path)
        assert step.install(MagicMock()) is False


# ── UvCheck ──────────────────────────────────────────────────

class TestUvCheck:
    @patch("shutil.which", return_value="/usr/bin/uv")
    def test_check_passes_when_uv_found(self, mock_which):
        step = UvCheck()
        assert step.check() is True

    @patch("subprocess.run")
    def test_install_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        step = UvCheck()
        console = MagicMock()
        assert step.install(console) is True

    @patch("shutil.which", return_value="/usr/bin/uv")
    def test_verify_calls_check(self, mock_which):
        step = UvCheck()
        assert step.verify() == step.check()

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

    def test_check_fails_on_ancient_sqlite(self):
        step = SQLiteCheck()
        with patch("services.setup._checks.sqlite3.sqlite_version_info", (3, 0, 0)):
            assert step.check() is False

    def test_install_fails(self):
        step = SQLiteCheck()
        assert step.install(MagicMock()) is False


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

    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "uv"))
    def test_install_fails_on_subprocess_error(self, mock_run, tmp_path):
        step = VenvCheck(tmp_path)
        console = MagicMock()
        assert step.install(console) is False
        assert step.check() is False


# ── DotenvxCheck ─────────────────────────────────────────────

class TestDotenvxCheck:
    @patch("shutil.which", return_value="/usr/bin/dotenvx")
    def test_check_passes(self, mock_which):
        step = DotenvxCheck()
        assert step.check() is True

    @patch("subprocess.run")
    def test_install_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        step = DotenvxCheck()
        console = MagicMock()
        assert step.install(console) is True

    @patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "sh"))
    def test_install_fails_subprocess_error(self, mock_run):
        step = DotenvxCheck()
        console = MagicMock()
        assert step.install(console) is False

    @patch("shutil.which", return_value="/usr/bin/dotenvx")
    def test_verify_calls_check(self, mock_which):
        step = DotenvxCheck()
        assert step.verify() == step.check()

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

class TestConfigValidators:
    def test_validate_port(self):
        assert _validate_port("8080") is True
        assert isinstance(_validate_port("0"), str)
        assert isinstance(_validate_port("70000"), str)
        assert isinstance(_validate_port("abc"), str)

    def test_validate_url(self):
        assert _validate_url("http://localhost:8080") is True
        assert _validate_url("https://example.com:443") is True
        assert isinstance(_validate_url("localhost:8080"), str)
        assert isinstance(_validate_url("http://localhost"), str)


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

    @patch("questionary.text")
    @patch("questionary.select")
    @patch("questionary.confirm")
    def test_install_generates_env_file(self, mock_confirm, mock_select, mock_text, tmp_path):
        mock_text.return_value.ask.return_value = "custom-val"
        mock_select.return_value.ask.return_value = "choice-val"
        mock_confirm.return_value.ask.return_value = False
        
        step = EnvConfig(tmp_path)
        console = MagicMock()
        assert step.install(console) is True
        
        env_content = (tmp_path / ".env").read_text()
        assert "RP_DB_PATH=custom-val" in env_content
        assert "RP_LOG_LEVEL=choice-val" in env_content

    @patch("questionary.text")
    @patch("questionary.confirm")
    def test_install_aborts_on_ctrl_c(self, mock_confirm, mock_text, tmp_path):
        mock_text.return_value.ask.return_value = None # Simulates Ctrl-C
        
        step = EnvConfig(tmp_path)
        console = MagicMock()
        assert step.install(console) is False

    def test_read_env_values_with_noise(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# Comment\n"
            " \n"
            "VAR1=VAL1\n"
            "VAR2 = VAL2 \n"
            "INVALID_LINE\n"
        )
        values = _read_env_values(env_file)
        assert values == {"VAR1": "VAL1", "VAR2": "VAL2"}

    def test_validate_port_edge_cases(self):
        assert _validate_port("1") is True
        assert _validate_port("65535") is True
        assert _validate_port("-1") == "Port must be 1-65535"
        assert _validate_port("65536") == "Port must be 1-65535"
        assert _validate_port("abc") == "Must be a number"

    def test_validate_url_edge_cases(self):
        assert _validate_url("http://localhost:80") is True
        assert _validate_url("https://pepers.ai:443") is True
        assert _validate_url("not-a-url") == "Must be a valid URL (e.g. http://localhost:8769)"
        assert _validate_url("http://no-port") == "Must be a valid URL (e.g. http://localhost:8769)"

    @patch("questionary.text")
    @patch("questionary.confirm")
    @patch("questionary.select")
    def test_install_with_custom_vars(self, mock_select, mock_confirm, mock_text, tmp_path):
        # 27 standard variables. All will ask for text except those with "choice:"
        # Let's count them:
        # port (8), url (4), path (3), text (9), choice (3)
        # Total text questions = 8 + 4 + 3 + 9 = 24

        # mock all standard text responses
        standard_responses = ["std_val"] * 24
        # then custom var loop: key, val, next key empty
        custom_responses = ["CUSTOM_K", "CUSTOM_V", ""]
        
        mock_text.return_value.ask.side_effect = standard_responses + custom_responses
        mock_select.return_value.ask.return_value = "std_choice"
        mock_confirm.return_value.ask.side_effect = [True] # want custom vars
        
        step = EnvConfig(tmp_path)
        console = MagicMock()
        assert step.install(console) is True
        
        content = (tmp_path / ".env").read_text()
        assert "CUSTOM_K=CUSTOM_V" in content
        assert "std_val" in content
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

    @patch.object(EnvConfig, "_reconcile_services_after_port_change")
    @patch.object(EnvConfig, "_auto_resolve_internal_port_conflicts", return_value=True)
    def test_install_defaults_reconciles_when_ports_remapped(
        self,
        _mock_remap,
        mock_reconcile,
        tmp_path,
    ):
        step = EnvConfig(tmp_path)
        console = MagicMock()
        assert step.install_defaults(console) is True
        mock_reconcile.assert_called_once()

    @patch.object(EnvConfig, "_reconcile_services_after_port_change")
    @patch.object(EnvConfig, "_auto_resolve_internal_port_conflicts", return_value=True)
    @patch("questionary.text")
    @patch("questionary.select")
    @patch("questionary.confirm")
    def test_install_reconciles_when_ports_remapped(
        self,
        mock_confirm,
        mock_select,
        mock_text,
        _mock_remap,
        mock_reconcile,
        tmp_path,
    ):
        mock_text.return_value.ask.return_value = "custom-val"
        mock_select.return_value.ask.return_value = "choice-val"
        mock_confirm.return_value.ask.return_value = False
        step = EnvConfig(tmp_path)
        console = MagicMock()
        assert step.install(console) is True
        mock_reconcile.assert_called_once()

    @patch.object(EnvConfig, "_compose_service_owns_port", return_value=False)
    @patch("services.setup._config._is_expected_service_on_port", return_value=True)
    @patch("services.setup._config._port_in_use")
    def test_auto_resolve_remaps_expected_service_port_when_not_owned_by_compose(
        self,
        mock_port_in_use,
        _mock_expected,
        _mock_owned,
        tmp_path,
    ):
        mock_port_in_use.side_effect = lambda port: port == 8776
        step = EnvConfig(tmp_path)
        values = {
            "RP_DISCOVERY_PORT": "8770",
            "RP_ANALYZER_PORT": "8771",
            "RP_EXTRACTOR_PORT": "8772",
            "RP_VALIDATOR_PORT": "8773",
            "RP_CODEGEN_PORT": "8774",
            "RP_ORCHESTRATOR_PORT": "8775",
            "RP_MCP_PORT": "8776",
        }

        changed = step._auto_resolve_internal_port_conflicts(values, MagicMock())

        assert changed is True
        assert values["RP_MCP_PORT"] == "8777"

    @patch.object(EnvConfig, "_compose_service_owns_port", return_value=True)
    @patch("services.setup._config._is_expected_service_on_port", return_value=True)
    @patch("services.setup._config._port_in_use")
    def test_auto_resolve_keeps_expected_service_port_when_owned_by_compose(
        self,
        mock_port_in_use,
        _mock_expected,
        _mock_owned,
        tmp_path,
    ):
        mock_port_in_use.side_effect = lambda port: port == 8776
        step = EnvConfig(tmp_path)
        values = {
            "RP_DISCOVERY_PORT": "8770",
            "RP_ANALYZER_PORT": "8771",
            "RP_EXTRACTOR_PORT": "8772",
            "RP_VALIDATOR_PORT": "8773",
            "RP_CODEGEN_PORT": "8774",
            "RP_ORCHESTRATOR_PORT": "8775",
            "RP_MCP_PORT": "8776",
        }

        changed = step._auto_resolve_internal_port_conflicts(values, MagicMock())

        assert changed is False
        assert values["RP_MCP_PORT"] == "8776"


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

    @patch.object(ExternalServiceCheck, "_runtime_dep_health", return_value=None)
    @patch("requests.get")
    def test_check_prefers_new_env_key_over_legacy(self, mock_get, _mock_runtime):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"service": "cas_service", "status": "ok"}
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
        assert mock_get.call_args_list[0].args[0] == "http://new:2/health"
        assert mock_get.call_args_list[0].kwargs["timeout"] == 5

    @patch.object(ExternalServiceCheck, "_runtime_dep_health")
    @patch.object(ExternalServiceCheck, "_discover_running_url", return_value=None)
    @patch("requests.get")
    def test_check_fails_when_host_is_up_but_orchestrator_cannot_reach_service(
        self,
        mock_get,
        _mock_discover,
        mock_runtime_dep,
    ):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "service": "cas-service",
            "status": "ok",
        }
        mock_runtime_dep.return_value = {
            "url": "http://host.docker.internal:8760",
            "healthy": False,
        }
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8760",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        with patch.dict(
            os.environ,
            {"RP_VALIDATOR_CAS_URL": "http://localhost:8760"},
            clear=False,
        ):
            step = ExternalServiceCheck(svc)
            assert step.check() is False
        assert "host.docker.internal:8760" in step._host_only_warning("http://localhost:8760")

    def test_runtime_url_matches_localhost_and_host_gateway(self):
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        step = ExternalServiceCheck(svc)
        assert step._runtime_url_matches_local_target(
            "http://localhost:8760",
            "http://host.docker.internal:8760",
        ) is True

    @patch("services.setup._config._port_in_use", side_effect=lambda port: port == 8760)
    @patch.object(ExternalServiceCheck, "_probe_effective", return_value=False)
    def test_suggest_clean_local_url_prefers_default_port_when_free(
        self,
        _mock_probe_effective,
        _mock_port_in_use,
    ):
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        step = ExternalServiceCheck(svc)
        assert step._suggest_clean_local_url("http://localhost:8760") == "http://localhost:8769"

    @patch.object(ExternalServiceCheck, "_persist_url")
    @patch.object(ExternalServiceCheck, "_suggest_clean_local_url", return_value="http://localhost:8769")
    @patch.object(
        ExternalServiceCheck,
        "_host_only_warning",
        return_value="CAS Service responds on the host but not from containers.",
    )
    def test_auto_rehome_host_only_url_persists_clean_target(
        self,
        _mock_warning,
        _mock_suggest,
        mock_persist,
    ):
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "setup_hint": "Install test service",
        }
        step = ExternalServiceCheck(svc)
        console = MagicMock()
        assert step._auto_rehome_host_only_url(console, preferred_url="http://localhost:8760") is True
        assert step._active_url == "http://localhost:8769"
        mock_persist.assert_called_once_with("http://localhost:8769", console)

    def test_external_service_constants_are_aligned(self):
        by_name = {svc["name"]: svc for svc in _EXTERNAL_SERVICES}
        assert by_name["CAS Service"]["env_urls"][0] == "RP_VALIDATOR_CAS_URL"
        assert by_name["RAG Service"]["env_urls"][0] == "RP_EXTRACTOR_RAG_URL"
        assert by_name["CAS Service"]["setup_cmd"] == "cas-setup"
        assert by_name["RAG Service"]["setup_cmd"] == "rag-setup"
        assert "cas-service.service" in by_name["CAS Service"]["systemd_units"]
        assert "raganything.service" in by_name["RAG Service"]["systemd_units"]
        assert "Ollama" not in by_name

    def test_persist_url_silent_updates_all_alias_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "RP_EXTRACTOR_RAG_URL=http://localhost:8767\n"
            "RP_RAG_QUERY_URL=http://localhost:8767\n"
            "RP_RAG_URL=http://localhost:8767\n"
        )
        svc = next(s for s in _EXTERNAL_SERVICES if s["name"] == "RAG Service")
        step = ExternalServiceCheck(svc, project_root=tmp_path)
        step._persist_url_silent("http://localhost:9900")
        values = _read_env_values(env_file)
        assert values["RP_EXTRACTOR_RAG_URL"] == "http://localhost:9900"
        assert values["RP_RAG_QUERY_URL"] == "http://localhost:9900"
        assert values["RP_RAG_URL"] == "http://localhost:9900"

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

    @patch("services.setup._services.questionary.confirm")
    def test_install_aborted_by_user(self, mock_confirm):
        svc = {"name": "S", "default_url": "h", "setup_cmd": "cmd", "setup_hint": "hint"}
        check = ExternalServiceCheck(svc)
        mock_confirm.return_value.ask.return_value = False
        assert check.install(MagicMock()) is False

    @patch("services.setup._services.shutil.which", return_value=None)
    @patch("services.setup._services.ExternalServiceCheck._local_setup_fallback", return_value=None)
    @patch("services.setup._services.questionary.confirm")
    def test_install_no_paths_found(self, mock_confirm, mock_fallback, mock_which):
        svc = {"name": "S", "default_url": "h", "setup_hint": "hint"}
        check = ExternalServiceCheck(svc)
        mock_confirm.return_value.ask.return_value = True
        console = MagicMock()
        assert check.install(console) is False
        console.print.assert_called()

    def test_local_setup_fallback_discovery(self, tmp_path):
        # Create a fake sibling repo structure
        # ../cas-service/.venv/bin/python
        repo_dir = tmp_path / "cas-service"
        repo_dir.mkdir()
        (repo_dir / ".venv" / "bin").mkdir(parents=True)
        python_bin = repo_dir / ".venv" / "bin" / "python"
        python_bin.touch()
        
        svc = {
            "name": "CAS",
            "local_repo": "cas-service",
            "local_module": "cas.main",
            "default_url": "http://h",
        }
        check = ExternalServiceCheck(svc)
        
        # Patch Path.resolve() to point to pepers/services/setup/main.py
        pepers_dir = tmp_path / "pepers"
        pepers_dir.mkdir()
        main_file = pepers_dir / "services" / "setup" / "main.py"
        main_file.parent.mkdir(parents=True)
        
        with patch("services.setup._services.Path.resolve", return_value=main_file):
            cmd, cwd, env, display = check._local_setup_fallback()
            assert str(cwd) == str(repo_dir)
            assert "cas.main" in cmd
            assert str(python_bin) in cmd[0]


class TestExternalServicePersistenceCheck:
    @patch.object(ExternalServiceCheck, "check", return_value=True)
    @patch.object(
        ExternalServiceCheck,
        "check_boot_persistence",
        return_value=(True, "systemd:cas-service.service"),
    )
    def test_check_passes_when_persistent(self, mock_persist, mock_check):
        svc = _EXTERNAL_SERVICES[0]
        step = ExternalServicePersistenceCheck(svc)
        assert step.check() is True

    @patch.object(ExternalServiceCheck, "check", return_value=True)
    @patch.object(
        ExternalServiceCheck,
        "check_boot_persistence",
        return_value=(False, "missing"),
    )
    def test_check_fails_when_not_persistent(self, mock_persist, mock_check):
        svc = _EXTERNAL_SERVICES[0]
        step = ExternalServicePersistenceCheck(svc)
        assert step.check() is False

    @patch.object(ExternalServiceCheck, "check", return_value=False)
    def test_check_skips_when_service_down(self, mock_check):
        svc = _EXTERNAL_SERVICES[0]
        step = ExternalServicePersistenceCheck(svc)
        assert step.check() is True

    @patch.object(ExternalServiceCheck, "check", return_value=False)
    def test_install_skips_when_service_down(self, mock_check):
        svc = _EXTERNAL_SERVICES[0]
        step = ExternalServicePersistenceCheck(svc)
        console = MagicMock()
        assert step.install(console) is True
        console.print.assert_called()

    @patch.object(ExternalServiceCheck, "check", return_value=True)
    @patch.object(
        ExternalServiceCheck,
        "check_boot_persistence",
        return_value=(False, "missing"),
    )
    def test_install_shows_instructions_when_missing(self, mock_persist, mock_check):
        svc = _EXTERNAL_SERVICES[0]
        step = ExternalServicePersistenceCheck(svc)
        console = MagicMock()
        assert step.install(console) is False
        console.print.assert_called()

    def test_services_step_includes_reachability_and_persistence(self):
        steps = get_services_steps()
        assert len(steps) == len(_EXTERNAL_SERVICES) * 2
        assert isinstance(steps[0], ExternalServiceCheck)
        assert isinstance(steps[1], ExternalServicePersistenceCheck)

    @patch("services.setup._services.subprocess.run")
    def test_systemd_boot_enabled_detects_unit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="enabled\n")
        svc = {
            "name": "CAS Service",
            "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
            "default_url": "http://localhost:8769",
            "health_path": "/health",
            "systemd_units": ["cas-service.service"],
        }
        step = ExternalServiceCheck(svc)
        assert step._systemd_boot_enabled() == "cas-service.service"


# ── MCP config ───────────────────────────────────────────────

class TestMcpConfigStep:
    @patch.object(AggregatedHealthCheck, "verify_internal", return_value=False)
    def test_install_requires_healthy_internal_stack_before_writing_config(self, _mock_verify, tmp_path):
        step = McpConfigStep()
        console = MagicMock()
        config_path = tmp_path / ".claude.json"

        with patch("services.setup._mcp_config.Path.home", return_value=tmp_path), \
             patch("services.setup._mcp_config.Path.cwd", return_value=tmp_path):
            assert step.install(console) is False
            assert not config_path.exists()

    @patch.object(AggregatedHealthCheck, "verify_internal", return_value=True)
    def test_install_writes_claude_config_and_verify_passes(self, _mock_verify, tmp_path):
        step = McpConfigStep()
        console = MagicMock()
        config_path = tmp_path / ".claude.json"

        with patch("services.setup._mcp_config.Path.home", return_value=tmp_path), \
             patch("services.setup._mcp_config.Path.cwd", return_value=tmp_path):
            assert step.check() is False
            assert step.install(console) is True
            assert config_path.exists()

            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["pepers"]["type"] == "sse"
            assert data["mcpServers"]["pepers"]["url"] == "http://localhost:8776/sse"
            assert step.verify() is True

    @patch.object(AggregatedHealthCheck, "verify_internal", return_value=True)
    def test_install_skips_invalid_json_if_other_target_is_writable(self, _mock_verify, tmp_path):
        step = McpConfigStep()
        console = MagicMock()
        bad = tmp_path / ".claude.json"
        good = tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
        bad.write_text("{not json")

        with patch("services.setup._mcp_config.Path.home", return_value=tmp_path), \
             patch("services.setup._mcp_config.Path.cwd", return_value=tmp_path), \
             patch("services.setup._mcp_config.platform.system", return_value="Linux"):
            assert step.install(console) is True
            assert good.exists()

    def test_entry_matches_accepts_absolute_npx_command(self):
        step = McpConfigStep()
        entry = {
            "type": "stdio",
            "command": "/usr/local/bin/npx",
            "args": ["-y", "mcp-remote", "http://localhost:8786/sse", "--transport", "sse-only"],
            "env": {"PATH": "/usr/local/bin"},
        }
        assert step._entry_matches(entry, "http://localhost:8786/sse") is True

    def test_build_pepers_entry_uses_url_positional_for_desktop_bridge(self):
        step = McpConfigStep()
        step._desktop_bridge_cache = ("/usr/local/bin/npx", {"PATH": "/usr/local/bin"})
        entry = step._build_pepers_entry(
            url="http://localhost:8786/sse",
            for_desktop=True,
        )
        assert entry["command"] == "/usr/local/bin/npx"
        assert entry["args"] == [
            "-y",
            "mcp-remote",
            "http://localhost:8786/sse",
            "--transport",
            "sse-only",
        ]

    @patch("services.setup._cli_tools.NodeCheck")
    @patch.object(
        McpConfigStep,
        "_resolve_working_desktop_bridge",
        side_effect=[None, ("/usr/local/bin/npx", {"PATH": "/usr/local/bin"})],
    )
    @patch("services.setup._mcp_config.shutil.which", return_value="/usr/local/bin/npx")
    def test_ensure_npx_for_desktop_repairs_broken_runtime(
        self,
        _mock_which,
        _mock_bridge,
        mock_node_cls,
    ):
        node_step = MagicMock()
        node_step.check.return_value = False
        node_step.install.return_value = True
        mock_node_cls.return_value = node_step

        step = McpConfigStep()
        assert step._ensure_npx_for_desktop(MagicMock()) is True
        node_step.install.assert_called_once()


# ── AggregatedHealthCheck ────────────────────────────────────

class TestAggregatedHealthCheck:
    def test_check_false_until_first_run_then_true(self):
        """Aggregated check is pending until install() runs once."""
        step = AggregatedHealthCheck()
        assert step.check() is False
        step.install(MagicMock())
        assert step.check() is True

    def test_install_returns_true(self):
        """Install is informational, always succeeds."""
        step = AggregatedHealthCheck()
        console = MagicMock()
        assert step.install(console) is True

    @patch("services.setup._verify._check_http", return_value=True)
    def test_verify_true_after_successful_install(self, _mock_http):
        step = AggregatedHealthCheck()
        console = MagicMock()
        step.install(console)
        assert step.verify() is True

    @patch("services.setup._verify._check_http")
    def test_verify_internal_ignores_external_service_failures(self, mock_http):
        def fake_http(url, timeout=3.0, *, expected_service=None):
            if "11434" in url:
                return False
            return True

        mock_http.side_effect = fake_http
        step = AggregatedHealthCheck()
        assert step.verify_internal() is True

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

    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_uses_internal_ports_from_env_file(self, mock_http, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("RP_DISCOVERY_PORT=9900\n")
        step = AggregatedHealthCheck()
        console = MagicMock()
        with patch("services.setup._verify.Path.cwd", return_value=tmp_path):
            step.install(console)
        called_urls = [call.args[0] for call in mock_http.call_args_list]
        assert "http://localhost:9900/health" in called_urls

    @patch.object(EnvConfig, "_reconcile_services_after_port_change")
    @patch.object(EnvConfig, "_auto_resolve_internal_port_conflicts", return_value=True)
    @patch("services.setup._verify._check_http", return_value=True)
    def test_install_seeds_missing_internal_ports_before_remap(
        self,
        _mock_http,
        mock_remap,
        mock_reconcile,
        tmp_path,
    ):
        env_file = tmp_path / ".env"
        env_file.write_text("RP_DB_PATH=/tmp/test.db\n")
        step = AggregatedHealthCheck()
        console = MagicMock()
        with patch("services.setup._verify.Path.cwd", return_value=tmp_path):
            step.install(console)
        passed_values = mock_remap.call_args.args[0]
        assert passed_values["RP_DISCOVERY_PORT"] == "8770"
        assert passed_values["RP_ORCHESTRATOR_PORT"] == "8775"
        assert passed_values["RP_MCP_PORT"] == "8776"
        mock_reconcile.assert_called_once()

    @patch.object(
        AggregatedHealthCheck,
        "_wait_for_internal_services",
        return_value=([("Discovery", "http://localhost:8780/health", True, ":8780")], True, True),
    )
    @patch.object(AggregatedHealthCheck, "_maybe_auto_remap_internal_ports", return_value=False)
    @patch.object(AggregatedHealthCheck, "_maybe_auto_reconcile_internal_services", return_value=True)
    @patch.object(AggregatedHealthCheck, "_collect_rows")
    def test_install_auto_reconciles_when_internal_services_are_down(
        self,
        mock_collect,
        mock_reconcile,
        _mock_remap,
        mock_wait,
    ):
        mock_collect.return_value = (
            [("Discovery", "http://localhost:8770/health", False, ":8770")],
            False,
            False,
        )
        step = AggregatedHealthCheck()
        console = MagicMock()
        assert step.install(console) is True
        mock_reconcile.assert_called_once_with(console)
        mock_wait.assert_called_once()

    @patch.object(AggregatedHealthCheck, "_maybe_auto_reconcile_internal_services")
    @patch.object(
        AggregatedHealthCheck,
        "_wait_for_internal_services",
        return_value=([("Discovery", "http://localhost:8770/health", True, ":8770")], True, True),
    )
    @patch.object(AggregatedHealthCheck, "_maybe_auto_remap_internal_ports", return_value=True)
    def test_install_waits_after_port_remap_before_triggering_second_reconcile(
        self,
        _mock_remap,
        mock_wait,
        mock_reconcile,
    ):
        step = AggregatedHealthCheck()
        console = MagicMock()
        assert step.install(console) is True
        mock_wait.assert_called_once()
        mock_reconcile.assert_not_called()

    @patch.object(AggregatedHealthCheck, "_maybe_auto_remediate_ollama", return_value=True)
    @patch.object(AggregatedHealthCheck, "_maybe_auto_reconcile_internal_services", return_value=False)
    @patch.object(AggregatedHealthCheck, "_maybe_auto_remap_internal_ports", return_value=False)
    @patch.object(AggregatedHealthCheck, "_collect_rows")
    def test_install_rechecks_after_ollama_remediation(
        self,
        mock_collect,
        _mock_remap,
        _mock_reconcile,
        mock_ollama,
    ):
        mock_collect.side_effect = [
            (
                [
                    ("Discovery", "http://localhost:8770/health", True, ":8770"),
                    ("Ollama", "http://localhost:11434/", False, ""),
                ],
                False,
                True,
            ),
            (
                [
                    ("Discovery", "http://localhost:8770/health", True, ":8770"),
                    ("Ollama", "http://localhost:11434/", True, ""),
                ],
                True,
                True,
            ),
        ]
        step = AggregatedHealthCheck()
        console = MagicMock()
        assert step.install(console) is True
        mock_ollama.assert_called_once_with(console)

    @patch("services.setup._cli_tools.shutil.which", return_value="/usr/bin/ollama")
    @patch.object(AggregatedHealthCheck, "_wait_for_endpoint", return_value=True)
    @patch.object(AggregatedHealthCheck, "_start_local_ollama", return_value=True)
    @patch("services.setup._verify._check_http", return_value=False)
    def test_maybe_auto_remediate_ollama_starts_local_server_for_localhost(
        self,
        _mock_http,
        mock_start,
        mock_wait,
        _mock_which,
    ):
        step = AggregatedHealthCheck()
        console = MagicMock()
        with patch.dict(os.environ, {"RP_CODEGEN_OLLAMA_URL": "http://localhost:11434"}, clear=False):
            assert step._maybe_auto_remediate_ollama(console) is True
        mock_start.assert_called_once()
        mock_wait.assert_called_once()

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

    @patch("services.setup._verify._orchestrator_runtime_health")
    @patch("services.setup._verify._check_http", return_value=True)
    def test_collect_rows_prefers_orchestrator_view_for_external_services(
        self,
        _mock_http,
        mock_runtime_health,
    ):
        mock_runtime_health.return_value = {
            "external": {
                "deps": {
                    "cas": {
                        "url": "http://host.docker.internal:8760",
                        "healthy": False,
                    },
                },
            },
        }

        step = AggregatedHealthCheck()
        rows, all_ok, internal_ok = step._collect_rows()

        cas_row = next(row for row in rows if row[0] == "CAS Service")
        assert cas_row[1] == "http://host.docker.internal:8760/health"
        assert cas_row[2] is False
        assert "orchestrator cannot reach it" in cas_row[3]
        assert internal_ok is True
        assert all_ok is False


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

    @patch("services.setup._runner.run_steps")
    @patch("questionary.select")
    def test_run_interactive_menu_run_all_unresolved_includes_warn(self, mock_select, mock_run_steps):
        from services.setup._runner import run_interactive_menu

        warn_step = MagicMock()
        warn_step.name = "Warn"
        warn_step.description = "Warn step"
        warn_step.check.return_value = True
        warn_step.verify.return_value = False

        mock_select.return_value.ask.side_effect = ["run_all_unresolved", "exit"]
        console = MagicMock()

        run_interactive_menu([warn_step], console)
        assert mock_run_steps.call_count == 1

    @patch("services.setup._runner.run_steps")
    @patch("questionary.select")
    def test_run_interactive_menu_run_all_unresolved_uses_force_run(self, mock_select, mock_run_steps):
        from services.setup._runner import run_interactive_menu

        warn_step = MagicMock()
        warn_step.name = "Warn"
        warn_step.description = "Warn step"
        warn_step.check.return_value = True
        warn_step.verify.return_value = False

        mock_select.return_value.ask.side_effect = ["run_all_unresolved", "exit"]
        console = MagicMock()

        run_interactive_menu([warn_step], console)
        _, kwargs = mock_run_steps.call_args
        assert kwargs.get("force_run") is True

    def test_force_run_configured_step_verifies_without_install(self):
        from services.setup._runner import _run_single_step

        step = MagicMock()
        step.name = "Docker Compose"
        step.check.return_value = True
        step.verify.return_value = False
        step.auto_reconcile_when_configured = False

        console = MagicMock()
        console.status.return_value.__enter__ = MagicMock()
        console.status.return_value.__exit__ = MagicMock()

        status = _run_single_step(step, console, force_run=True)
        assert status == "warn"
        step.install.assert_not_called()
        step.verify.assert_called_once()

    def test_force_run_configured_step_without_verify_uses_check(self):
        from services.setup._runner import _run_single_step

        class LegacyStep:
            name = "Legacy"
            description = "Legacy step"

            def check(self):
                return True

            def install(self, _console):
                raise RuntimeError("should not install")

        console = MagicMock()
        console.status.return_value.__enter__ = MagicMock()
        console.status.return_value.__exit__ = MagicMock()

        status = _run_single_step(LegacyStep(), console, force_run=True)
        assert status == "ok"


# ── CLI main() ────────────────────────────────────────────────

class TestSetupMainCli:
    @patch("services.setup.main.Console")
    def test_help_flag_returns_zero(self, mock_console_cls):
        rc = setup_main.main(["--help"])
        assert rc == 0
        console = mock_console_cls.return_value
        console.print.assert_called()

    @patch("services.setup._runner.run_steps", return_value=True)
    @patch("services.setup.main.Console")
    def test_subcommands_use_run_steps(self, mock_console, mock_run_steps):
        for cmd in ["check", "config", "services", "docker", "verify"]:
            rc = setup_main.main([cmd])
            assert rc == 0
        assert mock_run_steps.call_count == 5

    @patch("services.setup.main.Console")
    def test_unknown_command_returns_one(self, mock_console):
        rc = setup_main.main(["bogus"])
        assert rc == 1
        # It prints unknown command THEN usage
        calls = mock_console.return_value.print.call_args_list
        assert any("[red]Unknown command: bogus[/]" in str(c) for c in calls)

    def test_project_root_discovery(self, tmp_path):
        # We need to make sure _project_root finds pyproject.toml in tmp_path
        (tmp_path / "pyproject.toml").touch()
        # Mock Path.cwd() to be tmp_path
        with patch("services.setup.main.Path.cwd", return_value=tmp_path):
            with patch("services.setup.main.Path.resolve", return_value=tmp_path / "services" / "setup" / "main.py"):
                root = setup_main._project_root()
                assert root == tmp_path

    def test_all_steps_returns_list(self, tmp_path):
        steps = setup_main._all_steps(tmp_path)
        assert isinstance(steps, list)
        assert len(steps) > 0
        assert steps[-2].name == "Aggregated health check"
        assert steps[-1].name == "MCP Server -> Claude Code/Desktop"
