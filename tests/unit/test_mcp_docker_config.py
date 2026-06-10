"""Unit tests for MCP container environment configuration."""

from __future__ import annotations

import pytest

from cellin.mcp.config import storage_config_from_env


def test_storage_config_from_env_defaults_to_sqlite() -> None:
    config = storage_config_from_env({})

    assert config.memory.backend == "sqlite"
    assert config.graph.backend == "sqlite"
    assert config.vector.backend == "in_memory_vector_index"


def test_storage_config_from_env_supports_in_memory() -> None:
    config = storage_config_from_env({"CELLIN_BACKEND": "in_memory"})

    assert config.memory.backend == "in_memory"
    assert config.graph.backend == "in_memory"


def test_storage_config_from_env_supports_postgres() -> None:
    config = storage_config_from_env(
        {
            "CELLIN_BACKEND": "postgres",
            "CELLIN_CONNECTION_STRING": "postgresql://postgres:5432/cellin",
        }
    )

    assert config.memory.backend == "postgresql"
    assert config.graph.backend == "postgresql"
    assert config.memory.database_path == "postgresql://postgres:5432/cellin"


def test_storage_config_from_env_supports_neo4j_with_sqlite_memory() -> None:
    config = storage_config_from_env(
        {
            "CELLIN_BACKEND": "neo4j",
            "CELLIN_CONNECTION_STRING": "bolt://neo4j:7687",
        }
    )

    assert config.memory.backend == "sqlite"
    assert config.graph.backend == "neo4j"
    assert config.graph.database_path == "bolt://neo4j:7687"


def test_storage_config_from_env_requires_connection_for_remote_backend() -> None:
    with pytest.raises(ValueError, match="CELLIN_CONNECTION_STRING"):
        storage_config_from_env({"CELLIN_BACKEND": "postgres"})


def test_storage_config_from_env_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported CELLIN_BACKEND"):
        storage_config_from_env({"CELLIN_BACKEND": "oracle"})
