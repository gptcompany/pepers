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

import os
from dataclasses import dataclass, field
from pathlib import Path

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
    ...
