"""Configuration management for research pipeline services.

Loads configuration from environment variables with dotenvx integration.
Each service has a standard set of config fields plus service-specific ones.

Env var naming convention: RP_{SERVICE}_{FIELD}
- RP_DISCOVERY_PORT=8770
- RP_ANALYZER_PORT=8771
- RP_DB_PATH=/media/sam/1TB/research-pipeline/data/research.db
- RP_LOG_LEVEL=INFO

Usage:
    from shared.config import load_config, Config

    config = load_config("discovery")
    print(config.port)      # 8770
    print(config.db_path)   # /media/sam/1TB/research-pipeline/data/research.db
    print(config.log_level) # INFO

Design decisions:
- Env vars prefixed with RP_ (Research Pipeline) to avoid collisions
- dotenvx for encrypted secrets (API keys, tokens)
- Dataclass for type safety and IDE support
- Defaults for development, env vars for production
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "research.db"

# Service port assignments
SERVICE_PORTS: dict[str, int] = {
    "discovery": 8770,
    "analyzer": 8771,
    "extractor": 8772,
    "validator": 8773,
    "codegen": 8774,
    "orchestrator": 8775,
}


def _parse_float_env(name: str, default: str) -> float:
    """Parse float from environment variable with fallback on invalid values."""
    raw = os.environ.get(name, default)
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s invalid value '%s', using default %s", name, raw, default)
        return float(default)


# LLM temperature — 0 for deterministic output, configurable via env var
LLM_TEMPERATURE: float = _parse_float_env("RP_LLM_TEMPERATURE", "0")

# LLM seed — fixed seed for reproducibility, configurable via env var
LLM_SEED: int = int(os.environ.get("RP_LLM_SEED", "42"))


@dataclass
class Config:
    """Service configuration.

    Populated from environment variables with RP_ prefix.

    Attributes:
        service_name: Name of this service.
        port: TCP port to listen on.
        db_path: Path to SQLite database file.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        data_dir: Directory for data files.
    """

    service_name: str
    port: int = 0
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    log_level: str = "INFO"
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")


def load_config(service_name: str) -> Config:
    """Load configuration for a service from environment variables.

    Reads RP_{SERVICE}_{FIELD} env vars with sensible defaults.

    Args:
        service_name: Service name (discovery, analyzer, etc.).

    Returns:
        Populated Config dataclass.
    """
    prefix = service_name.upper()
    default_port = SERVICE_PORTS.get(service_name, 8770)

    # Port
    port_str = os.environ.get(f"RP_{prefix}_PORT", "")
    if port_str:
        port = int(port_str)
    else:
        logger.warning("RP_%s_PORT not set, using default %d", prefix, default_port)
        port = default_port

    # DB path
    db_path_str = os.environ.get("RP_DB_PATH", "")
    if db_path_str:
        db_path = Path(db_path_str)
    else:
        logger.warning("RP_DB_PATH not set, using default %s", DEFAULT_DB_PATH)
        db_path = DEFAULT_DB_PATH

    # Log level
    log_level = os.environ.get("RP_LOG_LEVEL", "INFO").upper()

    # Data dir
    data_dir_str = os.environ.get("RP_DATA_DIR", "")
    if data_dir_str:
        data_dir = Path(data_dir_str)
    else:
        data_dir = Path(__file__).parent.parent / "data"

    return Config(
        service_name=service_name,
        port=port,
        db_path=db_path,
        log_level=log_level,
        data_dir=data_dir,
    )
