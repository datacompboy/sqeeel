"""
This package will contain database-specific modules.
"""
from .base import ExecResult, Executor, DatabaseModule
from .docker_db import DockerExecutor
from .postgresql import PostgresModule
from .mariadb import MariaDBModule
from .cockroachdb import CockroachModule
from .yugabytedb import YugabyteModule
from .firebolt import FireboltModule
from .scylladb import ScyllaDBModule

_MODULES = {
    m.name: m for m in [
        PostgresModule(),
        MariaDBModule(),
        CockroachModule(),
        YugabyteModule(),
        FireboltModule(),
        ScyllaDBModule(),
    ]
}

def get_all_db_modules():
    return _MODULES

def get_db_module(name: str) -> DatabaseModule:
    if name not in _MODULES:
        raise ValueError(f"Unknown database type: {name}. Supported types: {', '.join(_MODULES.keys())}")
    return _MODULES[name]

__all__ = ["Executor", "ExecResult", "DockerExecutor", "get_all_db_modules", "get_db_module"]