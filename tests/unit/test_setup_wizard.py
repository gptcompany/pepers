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
        mock_run.assert_called_with(["docker", "compose", "up", "-d"], cwd=tmp_path, check=True, text=True)

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
        mock_get.assert_called_once_with("http://new:2/health", timeout=5)

    def test_external_service_constants_are_aligned(self):
        by_name = {svc["name"]: svc for svc in _EXTERNAL_SERVICES}
        assert by_name["CAS Service"]["env_urls"][0] == "RP_VALIDATOR_CAS_URL"
        assert by_name["RAG Service"]["env_urls"][0] == "RP_EXTRACTOR_RAG_URL"
        assert by_name["CAS Service"]["setup_cmd"] == "cas-setup"
        assert by_name["RAG Service"]["setup_cmd"] == "rag-setup"
        assert "cas-service.service" in by_name["CAS Service"]["systemd_units"]
        assert "raganything.service" in by_name["RAG Service"]["systemd_units"]
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
