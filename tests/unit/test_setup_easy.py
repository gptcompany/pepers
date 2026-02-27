"""Unit tests for PePeRS easy (non-interactive) setup mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.setup._config import EnvConfig, _CONFIG_VARS
from services.setup._runner import run_noninteractive
from services.setup._verify import (
    TIER_CORE,
    TIER_EXTERNAL,
    TIER_OPTIONAL,
    Readiness,
    SetupVerdict,
    compute_verdict,
    print_verdict,
)
from services.setup import main as setup_main


# ── helpers ──────────────────────────────────────────────────


def _make_step(*, check_ok: bool = True, install_ok: bool = True, verify_ok: bool = True):
    step = MagicMock()
    step.name = "FakeStep"
    step.check.return_value = check_ok
    step.install.return_value = install_ok
    step.verify.return_value = verify_ok
    return step


def _console() -> MagicMock:
    return MagicMock()


# ── TestRunNoninteractive ────────────────────────────────────


class TestRunNoninteractive:
    def test_step_passes_check_returns_ok_no_install(self):
        step = _make_step(check_ok=True)
        results = run_noninteractive([step], _console())
        assert results == [("FakeStep", "ok")]
        step.install.assert_not_called()

    def test_step_fails_check_installs_and_verifies(self):
        step = _make_step(check_ok=False, install_ok=True, verify_ok=True)
        results = run_noninteractive([step], _console())
        assert results == [("FakeStep", "ok")]
        step.install.assert_called_once()
        step.verify.assert_called_once()

    def test_install_failure_returns_failed(self):
        step = _make_step(check_ok=False, install_ok=False)
        results = run_noninteractive([step], _console())
        assert results == [("FakeStep", "failed")]

    def test_check_only_mode_returns_unavailable(self):
        step = _make_step(check_ok=False)
        results = run_noninteractive([step], _console(), check_only=True)
        assert results == [("FakeStep", "unavailable")]
        step.install.assert_not_called()

    def test_check_only_mode_passes_returns_ok(self):
        step = _make_step(check_ok=True)
        results = run_noninteractive([step], _console(), check_only=True)
        assert results == [("FakeStep", "ok")]

    def test_no_questionary_call_in_code(self):
        """run_noninteractive must never call questionary."""
        import ast
        import inspect
        import services.setup._runner as runner_mod

        source = inspect.getsource(runner_mod.run_noninteractive)
        tree = ast.parse(source)
        questionary_methods = {"confirm", "select", "text"}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "questionary"
                and node.attr in questionary_methods
            ):
                raise AssertionError(
                    f"run_noninteractive calls questionary.{node.attr}"
                )

    def test_multiple_steps_all_reported(self):
        s1 = _make_step(check_ok=True)
        s1.name = "Step1"
        s2 = _make_step(check_ok=False, install_ok=True, verify_ok=True)
        s2.name = "Step2"
        s3 = _make_step(check_ok=False, install_ok=False)
        s3.name = "Step3"
        results = run_noninteractive([s1, s2, s3], _console())
        assert [r[0] for r in results] == ["Step1", "Step2", "Step3"]
        assert [r[1] for r in results] == ["ok", "ok", "failed"]

    def test_check_exception_treated_as_failure(self):
        step = _make_step(check_ok=False, install_ok=True, verify_ok=True)
        step.check.side_effect = RuntimeError("boom")
        results = run_noninteractive([step], _console())
        assert results == [("FakeStep", "ok")]


# ── TestEnvConfigInstallDefaults ─────────────────────────────


class TestEnvConfigInstallDefaults:
    def test_generates_env_with_all_defaults(self, tmp_path):
        cfg = EnvConfig(tmp_path)
        console = _console()
        assert cfg.install_defaults(console) is True

        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        for env_name, _desc, _default, _validator in _CONFIG_VARS:
            assert f"{env_name}=" in content

    def test_preserves_existing_values(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("RP_DB_PATH=/custom/path\n")

        cfg = EnvConfig(tmp_path)
        cfg.install_defaults(_console())

        content = env_path.read_text()
        assert "RP_DB_PATH=/custom/path" in content

    def test_idempotent(self, tmp_path):
        cfg = EnvConfig(tmp_path)
        console = _console()
        cfg.install_defaults(console)
        first = (tmp_path / ".env").read_text()
        cfg.install_defaults(console)
        second = (tmp_path / ".env").read_text()
        assert first == second

    def test_resolves_root_placeholder(self, tmp_path):
        cfg = EnvConfig(tmp_path)
        cfg.install_defaults(_console())
        content = (tmp_path / ".env").read_text()
        assert "{root}" not in content
        assert str(tmp_path) in content


# ── TestComputeVerdict ───────────────────────────────────────


class TestComputeVerdict:
    def test_all_core_ok_is_ready(self):
        results = [("A", "ok"), ("B", "ok")]
        tier_map = {"A": TIER_CORE, "B": TIER_CORE}
        v = compute_verdict(results, tier_map)
        assert v.readiness == Readiness.READY
        assert v.core_failed == []

    def test_core_failed_is_not_ready(self):
        results = [("A", "ok"), ("B", "failed")]
        tier_map = {"A": TIER_CORE, "B": TIER_CORE}
        v = compute_verdict(results, tier_map)
        assert v.readiness == Readiness.NOT_READY
        assert "B" in v.core_failed

    def test_external_down_is_ready_with_limitations(self):
        results = [("A", "ok"), ("Ext", "unavailable")]
        tier_map = {"A": TIER_CORE, "Ext": TIER_EXTERNAL}
        v = compute_verdict(results, tier_map)
        assert v.readiness == Readiness.READY_WITH_LIMITATIONS
        assert "Ext" in v.external_down

    def test_core_fail_plus_external_down_is_not_ready(self):
        results = [("A", "failed"), ("Ext", "unavailable")]
        tier_map = {"A": TIER_CORE, "Ext": TIER_EXTERNAL}
        v = compute_verdict(results, tier_map)
        assert v.readiness == Readiness.NOT_READY

    def test_unknown_tier_defaults_to_optional(self):
        results = [("Mystery", "ok")]
        v = compute_verdict(results, {})
        assert "Mystery" in v.optional_skipped


# ── TestPrintVerdict ─────────────────────────────────────────


class TestPrintVerdict:
    def test_ready_banner_green(self):
        v = SetupVerdict(readiness=Readiness.READY)
        console = _console()
        print_verdict(v, console)
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "green" in output
        assert "READY" in output

    def test_not_ready_shows_core_failed(self):
        v = SetupVerdict(
            readiness=Readiness.NOT_READY,
            core_failed=["Docker"],
        )
        console = _console()
        print_verdict(v, console)
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "Docker" in output

    def test_limitations_shows_external_down(self):
        v = SetupVerdict(
            readiness=Readiness.READY_WITH_LIMITATIONS,
            external_down=["CAS Service"],
        )
        console = _console()
        print_verdict(v, console)
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "CAS Service" in output

    def test_optional_skipped_hints_guided(self):
        v = SetupVerdict(
            readiness=Readiness.READY,
            optional_skipped=["Ollama"],
        )
        console = _console()
        print_verdict(v, console)
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "guided" in output


# ── TestEasyMode (CLI routing) ───────────────────────────────


class TestEasyMode:
    @patch("services.setup.main._easy_mode", return_value=0)
    @patch("services.setup.main.Console")
    def test_default_command_routes_to_easy(self, mock_console, mock_easy):
        rc = setup_main.main([])
        assert rc == 0
        mock_easy.assert_called_once()

    @patch("services.setup.main._easy_mode", return_value=0)
    @patch("services.setup.main.Console")
    def test_explicit_easy_routes_to_easy(self, mock_console, mock_easy):
        rc = setup_main.main(["easy"])
        assert rc == 0
        mock_easy.assert_called_once()

    @patch("services.setup._runner.run_interactive_menu", return_value=True)
    @patch("services.setup.main.Console")
    def test_all_routes_to_guided(self, mock_console, mock_menu):
        rc = setup_main.main(["all"])
        assert rc == 0
        mock_menu.assert_called_once()

    @patch("services.setup._runner.run_interactive_menu", return_value=True)
    @patch("services.setup.main.Console")
    def test_guided_routes_to_interactive(self, mock_console, mock_menu):
        rc = setup_main.main(["guided"])
        assert rc == 0
        mock_menu.assert_called_once()

    @patch("services.setup.main._easy_mode", return_value=1)
    @patch("services.setup.main.Console")
    def test_easy_mode_propagates_exit_code(self, mock_console, mock_easy):
        rc = setup_main.main([])
        assert rc == 1
