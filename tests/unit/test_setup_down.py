"""Unit tests for pepers-setup down and Docker boot check."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.setup._docker import DockerBootCheck, DockerComposeDown, get_down_steps
from services.setup.main import SUBCOMMANDS


# ---------------------------------------------------------------------------
# DockerComposeDown
# ---------------------------------------------------------------------------


class TestDockerComposeDown:
    def test_check_true_when_no_containers(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            assert step.check() is True

    def test_check_false_when_containers_running(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\ndef456\n")
            assert step.check() is False

    def test_check_true_on_file_not_found(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert step.check() is True

    def test_install_runs_compose_down(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            console = MagicMock()
            assert step.install(console) is True
            mock_run.assert_called_with(
                ["docker", "compose", "down"],
                cwd=tmp_path,
                check=True,
                text=True,
            )

    def test_install_returns_false_on_failure(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "docker"),
        ):
            console = MagicMock()
            assert step.install(console) is False

    def test_verify_calls_check(self, tmp_path):
        step = DockerComposeDown(tmp_path)
        with patch.object(step, "check", return_value=True) as mock_check:
            assert step.verify() is True
            mock_check.assert_called_once()

    def test_get_down_steps_returns_list(self, tmp_path):
        steps = get_down_steps(tmp_path)
        assert len(steps) == 1
        assert isinstance(steps[0], DockerComposeDown)


# ---------------------------------------------------------------------------
# DockerBootCheck
# ---------------------------------------------------------------------------


class TestDockerBootCheck:
    def test_docker_boot_enabled(self):
        step = DockerBootCheck()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="enabled\n")
            assert step.check() is True

    def test_docker_boot_disabled(self):
        step = DockerBootCheck()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="disabled\n")
            assert step.check() is False

    def test_docker_boot_no_systemd(self):
        step = DockerBootCheck()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert step.check() is True  # graceful skip

    def test_install_prints_warning(self):
        step = DockerBootCheck()
        console = MagicMock()
        result = step.install(console)
        assert result is False
        console.print.assert_called_once()

    def test_verify_calls_check(self):
        step = DockerBootCheck()
        with patch.object(step, "check", return_value=True) as mock_check:
            assert step.verify() is True
            mock_check.assert_called_once()


# ---------------------------------------------------------------------------
# Subcommand registration
# ---------------------------------------------------------------------------


class TestDownSubcommand:
    def test_down_subcommand_registered(self):
        assert "down" in SUBCOMMANDS

    @patch("services.setup._runner.run_steps", return_value=True)
    @patch("services.setup.main.Console")
    def test_down_cli_invocation(self, mock_console, mock_run_steps):
        from services.setup.main import main

        rc = main(["down"])
        assert rc == 0
        mock_run_steps.assert_called_once()
        steps = mock_run_steps.call_args[0][0]
        assert len(steps) == 1
        assert isinstance(steps[0], DockerComposeDown)
