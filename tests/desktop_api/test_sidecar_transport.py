"""Real-subprocess transport integration tests for the sidecar's own
half of FA-017 Round 7's protocol guarantees: handshake, STARTED-before-
handler, FIFO single-worker execution, malformed-request handling, and the
process-wide os._exit() fatal-transport primitive (never a thread-scoped
sys.exit()). Every test spawns a genuine `python -m file_agent.desktop_api`
child -- never an in-process fake -- so a fatal test case's os._exit() only
ever terminates the child, never the test runner itself.

Rust-side behavior (drain-to-EOF classification, the poisoned-generation
state machine, tests A-K from the design plan) belongs to the Rust
integration test suite (apps/desktop/src-tauri) once the Rust host exists
-- this file covers exactly what the Python sidecar itself is responsible
for proving.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)

if TYPE_CHECKING:
    from tests.desktop_api.conftest import SidecarProcess

PROTOCOL_NAME = "fileagent-desktop"
PROTOCOL_VERSION = 1


def _read_handshake(sidecar: SidecarProcess) -> dict[str, object]:
    return sidecar.read_line()


def test_handshake_is_first_line_and_exact(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar()
    handshake = _read_handshake(sidecar)
    assert handshake == {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
    }
    sidecar.close_stdin()
    assert sidecar.wait() == 0


def test_normal_round_trip_started_then_terminal(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar()
    _read_handshake(sidecar)
    sidecar.send("r1", "managed_roots.list", {})

    started = sidecar.read_line()
    assert started == {"id": "r1", "event": "started"}

    terminal = sidecar.read_line()
    assert terminal["id"] == "r1"
    assert terminal["ok"] is True
    sidecar.close_stdin()
    assert sidecar.wait() == 0


def test_fifo_ordering_two_requests_resolve_in_order(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    """Exactly one command executes at a time -- request ids are transport
    correlation only, never permission for concurrent execution."""
    sidecar = spawn_sidecar()
    _read_handshake(sidecar)
    sidecar.send("r1", "managed_roots.list", {})
    sidecar.send("r2", "managed_roots.list", {})

    frames = [sidecar.read_line() for _ in range(4)]
    ids_in_order = [f["id"] for f in frames]
    assert ids_in_order == ["r1", "r1", "r2", "r2"]
    assert frames[0]["event"] == "started"
    assert frames[1]["ok"] is True
    assert frames[2]["event"] == "started"
    assert frames[3]["ok"] is True
    sidecar.close_stdin()
    assert sidecar.wait() == 0


def test_malformed_request_with_recoverable_id_gets_protocol_error(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar()
    _read_handshake(sidecar)
    sidecar.send_raw(json.dumps({"id": "bad-1", "command": 12345, "params": {}}))

    frame = sidecar.read_line()
    assert frame["id"] == "bad-1"
    assert frame["ok"] is False
    assert frame["error"]["kind"] == "malformed_request"

    # The sidecar keeps running -- malformed input never enters the queue,
    # never becomes process-fatal.
    sidecar.send("r-after", "managed_roots.list", {})
    started = sidecar.read_line()
    assert started == {"id": "r-after", "event": "started"}
    sidecar.close_stdin()
    assert sidecar.wait() == 0


def test_malformed_request_with_no_recoverable_id_logs_to_stderr_only(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar()
    _read_handshake(sidecar)
    sidecar.send_raw("not even json{{{")

    sidecar.send("r-after", "managed_roots.list", {})
    started = sidecar.read_line()
    assert started == {"id": "r-after", "event": "started"}
    terminal = sidecar.read_line()
    assert terminal["ok"] is True
    sidecar.close_stdin()
    assert sidecar.wait() == 0


def test_unknown_command_resolves_as_per_request_fatal_not_process_fatal(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar()
    _read_handshake(sidecar)
    sidecar.send("r1", "file_agent.run_arbitrary_code", {})
    started = sidecar.read_line()
    assert started == {"id": "r1", "event": "started"}
    terminal = sidecar.read_line()
    assert terminal["ok"] is False
    assert terminal["error"]["kind"] == "fatal"
    assert terminal["error"]["code"] == "unknown_command"

    # Process survives -- a handler-level rejection is never process-fatal.
    sidecar.send("r2", "managed_roots.list", {})
    started2 = sidecar.read_line()
    assert started2 == {"id": "r2", "event": "started"}
    sidecar.close_stdin()
    assert sidecar.wait() == 0


# --- H1/H2/H3: process-wide os._exit() fatal transport failure -------------


def test_h1_started_write_failure_handler_never_executes_process_exits(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar(force_write_failure="started")
    _read_handshake(sidecar)
    sidecar.send("r1", "managed_roots.list", {})

    # No STARTED, no terminal -- the write raised before either was ever
    # observable; the process must actually exit (stdout EOF).
    with pytest.raises(EOFError):
        sidecar.read_line()
    exit_code = sidecar.wait()
    assert exit_code != 0


def test_h2_terminal_write_failure_after_durable_effect_process_exits(
    spawn_sidecar: Callable[..., SidecarProcess], tmp_path: Path
) -> None:
    """managed_roots.add is UNKNOWN_ON_DISCONNECT and genuinely persists a
    durable effect (a registered ManagedRoot row) before the terminal
    write is attempted and fails -- proving Python's own ground truth
    (the root WAS registered) is irrelevant to the transport-level
    guarantee: STARTED was observed, no terminal response ever arrives,
    and the process terminates rather than silently continuing. The
    durable effect is then verified independently, straight from the
    sidecar's own SQLite store, demonstrating the divergence is real, not
    hypothetical -- exactly why UNKNOWN, not "failed", is the correct
    classification (Round 7 §7)."""
    real_folder = tmp_path / "a_real_folder"
    real_folder.mkdir()

    sidecar = spawn_sidecar(force_write_failure="terminal")
    _read_handshake(sidecar)
    sidecar.send("r1", "managed_roots.add", {"path": str(real_folder)})

    started = sidecar.read_line()
    assert started == {"id": "r1", "event": "started"}
    with pytest.raises(EOFError):
        sidecar.read_line()
    exit_code = sidecar.wait()
    assert exit_code != 0

    app_paths = AppPaths.from_root(tmp_path / "sidecar_appdata")
    engine, session_factory = create_engine_and_session_factory(app_paths)
    try:
        store = FileAgentStore(session_factory)
        roots = store.list_managed_roots()
        assert any(r.path == real_folder.resolve() for r in roots)
    finally:
        engine.dispose()


def test_h3_reader_malformed_response_write_failure_process_exits(
    spawn_sidecar: Callable[..., SidecarProcess],
) -> None:
    sidecar = spawn_sidecar(force_write_failure="malformed")
    _read_handshake(sidecar)
    sidecar.send_raw(json.dumps({"id": "bad-1", "command": 999, "params": {}}))

    with pytest.raises(EOFError):
        sidecar.read_line()
    exit_code = sidecar.wait()
    assert exit_code != 0
