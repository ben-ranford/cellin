"""Environment-backed configuration for packaged MCP deployments."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from cellin.runtime import StorageBackendConfig, StorageConfig

SUPPORTED_MCP_BACKENDS: Final[frozenset[str]] = frozenset(
    {"in_memory", "neo4j", "postgres", "postgresql", "sqlite"}
)


def _backend_name(env: Mapping[str, str]) -> str:
    return env.get("CELLIN_BACKEND", "sqlite").strip().lower()


def _connection_string(env: Mapping[str, str], backend: str) -> str:
    value = env.get("CELLIN_CONNECTION_STRING", "").strip()
    if not value:
        raise ValueError(f"CELLIN_CONNECTION_STRING is required for `{backend}` backend.")
    return value


def storage_config_from_env(env: Mapping[str, str] | None = None) -> StorageConfig:
    """Resolve MCP storage config from CELLIN_* environment variables."""

    active_env = os.environ if env is None else env
    backend = _backend_name(active_env)
    vector_backend = StorageBackendConfig("in_memory_vector_index")

    if backend == "sqlite":
        return StorageConfig.with_sqlite_preset("cellin.sqlite")

    if backend == "in_memory":
        return StorageConfig.with_in_memory_preset()

    if backend in {"postgres", "postgresql"}:
        postgresql_backend = StorageBackendConfig(
            "postgresql",
            _connection_string(active_env, backend),
        )
        return StorageConfig(
            memory=postgresql_backend,
            graph=postgresql_backend,
            vector=vector_backend,
            representation=vector_backend,
        )

    if backend == "neo4j":
        return StorageConfig(
            memory=StorageBackendConfig("sqlite", "cellin.sqlite"),
            graph=StorageBackendConfig("neo4j", _connection_string(active_env, backend)),
            vector=vector_backend,
            representation=vector_backend,
        )

    supported = ", ".join(sorted(SUPPORTED_MCP_BACKENDS))
    raise ValueError(f"Unsupported CELLIN_BACKEND `{backend}`. Supported values: {supported}.")
