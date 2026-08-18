"""Sidecar process bootstrap: where the desktop application's own data
lives, and how FileAgentApplicationService is constructed against it.

Never inferred from any managed/scanned location -- see
file_agent.persistence.config.AppPaths's own docstring. This module is the
ONE place the desktop sidecar decides its app-data root; every other
package continues to receive AppPaths explicitly, exactly as before.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine

from alembic import command
from file_agent.application import FileAgentApplicationService
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.engine import DEFAULT_ALEMBIC_INI

_APP_DIRNAME = "FileAgent"
_APP_DATA_ROOT_OVERRIDE_ENV = "FILE_AGENT_DESKTOP_APP_DATA_ROOT"
"""Test/tooling-only override, mirroring alembic/env.py's own `-x
db_path=...` convention (see that module's docstring): the shipped
application itself always uses default_app_data_root()'s real
%APPDATA%/FileAgent location; only tests point the sidecar at an isolated
throwaway directory via this environment variable."""


def default_app_data_root() -> Path:
    """%APPDATA%/FileAgent on Windows (FA-017's only supported platform);
    ~/.file-agent as a defensive fallback if APPDATA is ever unset."""
    override = os.environ.get(_APP_DATA_ROOT_OVERRIDE_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / _APP_DIRNAME
    return Path.home() / ".file-agent"


def _upgrade_schema_to_head(app_paths: AppPaths) -> None:
    cfg = AlembicConfig(str(DEFAULT_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{app_paths.database_path}")
    command.upgrade(cfg, "head")


def build_application_service(
    app_paths: AppPaths | None = None,
) -> tuple[FileAgentApplicationService, Engine]:
    """Returns the service alongside its Engine so the sidecar's own
    shutdown path can dispose() it -- mirrors scripts/demo_preview.py's
    existing convention for the same Windows-file-lock reason."""
    resolved = (
        app_paths
        if app_paths is not None
        else AppPaths.from_root(default_app_data_root())
    )
    engine, session_factory = create_engine_and_session_factory(resolved)
    _upgrade_schema_to_head(resolved)
    store = FileAgentStore(session_factory)
    return FileAgentApplicationService(resolved, store), engine
