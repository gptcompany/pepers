"""Unit tests for shared/config.py — configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.config import DEFAULT_DB_PATH, SERVICE_PORTS, Config, load_config


class TestConstants:
    """Tests for module-level constants."""

    def test_default_db_path_is_path(self):
        assert isinstance(DEFAULT_DB_PATH, Path)
        assert "research.db" in str(DEFAULT_DB_PATH)

    def test_service_ports_all_present(self):
        expected = ["discovery", "analyzer", "extractor", "validator", "codegen", "orchestrator", "mcp"]
        for svc in expected:
            assert svc in SERVICE_PORTS

    def test_service_ports_range(self):
        for port in SERVICE_PORTS.values():
            assert 8770 <= port <= 8776

    def test_service_ports_unique(self):
        ports = list(SERVICE_PORTS.values())
        assert len(ports) == len(set(ports))


class TestConfig:
    """Tests for Config dataclass."""

    def test_creation_with_defaults(self):
        c = Config(service_name="test")
        assert c.service_name == "test"
        assert c.port == 0
        assert c.log_level == "INFO"

    def test_creation_with_all_fields(self):
        c = Config(
            service_name="discovery",
            port=8770,
            db_path=Path("/tmp/test.db"),
            log_level="DEBUG",
            data_dir=Path("/tmp/data"),
        )
        assert c.port == 8770
        assert str(c.db_path) == "/tmp/test.db"


class TestLoadConfig:
    """Tests for load_config()."""

    def test_defaults_no_env_vars(self, clean_env):
        config = load_config("discovery")
        assert config.service_name == "discovery"
        assert config.port == 8770
        assert config.log_level == "INFO"
        assert "research.db" in str(config.db_path)

    def test_port_from_env(self, clean_env):
        os.environ["RP_DISCOVERY_PORT"] = "9999"
        config = load_config("discovery")
        assert config.port == 9999

    def test_db_path_from_env(self, clean_env):
        os.environ["RP_DB_PATH"] = "/tmp/custom.db"
        config = load_config("discovery")
        assert str(config.db_path) == "/tmp/custom.db"

    def test_log_level_from_env(self, clean_env):
        os.environ["RP_LOG_LEVEL"] = "debug"
        config = load_config("discovery")
        assert config.log_level == "DEBUG"

    def test_data_dir_from_env(self, clean_env):
        os.environ["RP_DATA_DIR"] = "/tmp/mydata"
        config = load_config("discovery")
        assert str(config.data_dir) == "/tmp/mydata"

    def test_different_service_ports(self, clean_env):
        for svc, expected_port in SERVICE_PORTS.items():
            config = load_config(svc)
            assert config.port == expected_port, f"{svc} should default to {expected_port}"

    def test_unknown_service_defaults_to_8770(self, clean_env):
        config = load_config("unknown_service")
        assert config.port == 8770

    def test_partial_env_vars(self, clean_env):
        os.environ["RP_ANALYZER_PORT"] = "5555"
        config = load_config("analyzer")
        assert config.port == 5555
        assert config.log_level == "INFO"
        assert "research.db" in str(config.db_path)

    def test_invalid_port_raises(self, clean_env):
        os.environ["RP_DISCOVERY_PORT"] = "not_a_number"
        with pytest.raises(ValueError):
            load_config("discovery")
