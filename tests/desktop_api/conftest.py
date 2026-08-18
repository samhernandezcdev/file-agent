"""Shared fixtures for desktop_api tests -- mirrors tests/application/
conftest.py's own established pattern (real files, real sandbox, real
disjoint app-data root, real SQLite-backed FileAgentStore; no mocks),
duplicated per-package per this codebase's existing convention (see e.g.
recovery_engine/_paths.py's docstring for the precedent)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from file_agent.application import FileAgentApplicationService
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.scanner import SandboxRoot


@pytest.fixture
def sandbox_root(tmp_path: Path) -> SandboxRoot:
    root = tmp_path / "sandbox"
    root.mkdir()
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (root / directory).mkdir()
    return SandboxRoot.from_path(root)


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "appdata")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[FileAgentStore]:
    config = AppPaths.from_root(tmp_path / "store_appdata")
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    try:
        yield FileAgentStore(session_factory)
    finally:
        engine.dispose()


@pytest.fixture
def service(app_paths: AppPaths, store: FileAgentStore) -> FileAgentApplicationService:
    return FileAgentApplicationService(app_paths, store)


@pytest.fixture
def managed_root_id(
    service: FileAgentApplicationService, sandbox_root: SandboxRoot
) -> UUID:
    return service.add_managed_root(sandbox_root.path).id


@pytest.fixture
def make_source_file(sandbox_root: SandboxRoot) -> Callable[..., Path]:
    def _make(name: str = "report.txt", content: bytes = b"hello world") -> Path:
        path = sandbox_root.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    return _make


class SidecarProcess:
    """Thin, line-oriented wrapper around a real
    `python -m file_agent.desktop_api` child process -- every transport
    integration test drives the real sidecar, never an in-process fake."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc

    def read_line(self, *, timeout: float = 10.0) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if line == "":
            raise EOFError(
                "sidecar stdout closed (process exited) before a line arrived"
            )
        return dict(json.loads(line))

    def send(self, request_id: str, command: str, params: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"id": request_id, "command": command, "params": params}) + "\n"
        )
        self.proc.stdin.flush()

    def send_raw(self, line: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def close_stdin(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()

    def wait(self, *, timeout: float = 10.0) -> int:
        return self.proc.wait(timeout=timeout)

    def stderr_text(self) -> str:
        assert self.proc.stderr is not None
        return self.proc.stderr.read()


@pytest.fixture
def spawn_sidecar(
    tmp_path: Path,
) -> Iterator[Callable[..., SidecarProcess]]:
    spawned: list[subprocess.Popen[str]] = []

    def _spawn(*, force_write_failure: str | None = None) -> SidecarProcess:
        env = dict(os.environ)
        env["FILE_AGENT_DESKTOP_APP_DATA_ROOT"] = str(tmp_path / "sidecar_appdata")
        if force_write_failure is not None:
            env["FILE_AGENT_DESKTOP_TEST_FORCE_WRITE_FAILURE"] = force_write_failure
        proc = subprocess.Popen(
            [sys.executable, "-m", "file_agent.desktop_api"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        spawned.append(proc)
        return SidecarProcess(proc)

    try:
        yield _spawn
    finally:
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
