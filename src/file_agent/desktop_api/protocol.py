"""FA-017 desktop sidecar wire protocol: NDJSON framing over stdin/stdout,
the closed command/retry-safety manifest, and the single sanctioned
stdout writer.

This module owns no product logic -- it never calls
FileAgentApplicationService and never imports application/domain code.
See dispatcher.py/handlers.py for command execution, and __main__.py for
the reader/worker threads and process lifecycle that use these primitives.

Round 7 design (fa-001-domain-purring-seal.md) is the authority for every
ordering guarantee documented here; this module is the literal
implementation of §"SOLE PROTOCOL WRITER" / §"STARTED GUARANTEE" /
§"PROCESS-WIDE FATAL TRANSPORT FAILURE".
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Mapping
from enum import Enum
from importlib import resources
from typing import Any, TextIO

PROTOCOL_NAME = "fileagent-desktop"
PROTOCOL_VERSION = 1


class RetrySafety(str, Enum):
    """Retry-safety classification -- NOT "read-only vs mutating". See the
    commands.json manifest and FA-017 Round 2/3 design for the exact
    per-command rationale (e.g. analysis.run is SAFE_RETRY despite writing
    audit state; review.approve/skip are UNKNOWN_ON_DISCONNECT despite
    never moving a managed file)."""

    SAFE_RETRY = "safe_retry"
    UNKNOWN_ON_DISCONNECT = "unknown_on_disconnect"


class CommandCatalogEntry:
    __slots__ = ("name", "retry_safety")

    def __init__(self, name: str, retry_safety: RetrySafety) -> None:
        self.name = name
        self.retry_safety = retry_safety


def load_command_catalog() -> tuple[CommandCatalogEntry, ...]:
    """Parses commands.json -- the single, checked-in, cross-language
    contract/drift-guard manifest. This is metadata, never runtime
    authorization: nothing here decides whether a command may execute,
    only what its name and retry-safety classification are recorded as."""
    raw = (
        resources.files("file_agent.desktop_api")
        .joinpath("commands.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(raw)
    return tuple(
        CommandCatalogEntry(entry["name"], RetrySafety(entry["retry_safety"]))
        for entry in data["commands"]
    )


COMMAND_CATALOG: tuple[CommandCatalogEntry, ...] = load_command_catalog()
COMMAND_NAMES: frozenset[str] = frozenset(entry.name for entry in COMMAND_CATALOG)
RETRY_SAFETY_BY_COMMAND: Mapping[str, RetrySafety] = {
    entry.name: entry.retry_safety for entry in COMMAND_CATALOG
}


class ProtocolWriter:
    """The ONE sanctioned code path allowed to write to the real
    (pre-redirection) stdout stream after the startup handshake. Every
    post-handshake frame -- started, progress, terminal response,
    malformed-request response -- routes through `emit_frame`.

    `emit_frame` serializes, appends a newline, acquires the single lock,
    writes the complete line, flushes, and only releases the lock once the
    flush has completed. There is no partial-write/partial-flush state a
    concurrent caller can observe.
    """

    _TEST_FORCE_FAILURE_ENV = "FILE_AGENT_DESKTOP_TEST_FORCE_WRITE_FAILURE"
    """Test-only fault injection, gated by an environment variable that is
    never set in production: forces exactly one emit_frame call matching
    "started"/"terminal"/"malformed" to raise OSError, so transport
    integration tests can prove the real os._exit() fatal-shutdown path
    (protocol.fatal_transport_failure) actually fires end-to-end, run
    against a genuine subprocess -- never against the test runner's own
    process. See tests/desktop_api/test_sidecar_fatal_transport.py."""

    _TEST_CORRUPT_ENV = "FILE_AGENT_DESKTOP_TEST_CORRUPT_FRAME"
    """Test-only fault injection, distinct from _TEST_FORCE_FAILURE_ENV:
    instead of making a write FAIL (simulating a Python-detected transport
    failure -> os._exit()), this makes exactly one emit_frame call
    matching "started"/"terminal" write GENUINELY CORRUPT, non-JSON bytes
    to the real stream -- simulating the fd-1-bypass class of corruption
    Round 7 §6/§11 explicitly declines to claim impossible, so Rust's own
    corruption-detection/poisoned-generation path can be exercised against
    real garbled input rather than only a clean process exit. See
    apps/desktop/src-tauri/tests/manifest_drift_guard.rs and the sidecar
    corruption integration tests."""

    def __init__(self, real_stdout: TextIO) -> None:
        self._stream = real_stdout
        self._lock = threading.Lock()
        self._force_failure_on = os.environ.get(self._TEST_FORCE_FAILURE_ENV)
        self._already_forced_failure = False
        self._corrupt_on = os.environ.get(self._TEST_CORRUPT_ENV)
        self._already_corrupted = False

    def emit_frame(self, frame: Mapping[str, Any]) -> None:
        line = json.dumps(frame, separators=(",", ":")) + "\n"
        with self._lock:
            if self._should_force_failure(frame):
                self._already_forced_failure = True
                raise OSError(
                    f"test-injected write failure (target={self._force_failure_on})"
                )
            if self._should_corrupt(frame):
                self._already_corrupted = True
                self._stream.write("not-json-this-is-a-corrupted-frame{{{\n")
                self._stream.flush()
                return
            self._stream.write(line)
            self._stream.flush()

    def _should_corrupt(self, frame: Mapping[str, Any]) -> bool:
        target = self._corrupt_on
        if target is None or self._already_corrupted:
            return False
        if target == "started":
            return frame.get("event") == "started"
        if target == "terminal":
            return "ok" in frame
        return False

    def _should_force_failure(self, frame: Mapping[str, Any]) -> bool:
        target = self._force_failure_on
        if target is None or self._already_forced_failure:
            return False
        if target == "started":
            return frame.get("event") == "started"
        if target == "progress":
            return frame.get("event") == "progress"
        if target == "terminal":
            return "ok" in frame
        if target == "malformed":
            error = frame.get("error")
            return isinstance(error, dict) and error.get("kind") == "malformed_request"
        return False


def handshake_line() -> str:
    return (
        json.dumps(
            {"protocol": PROTOCOL_NAME, "protocol_version": PROTOCOL_VERSION},
            separators=(",", ":"),
        )
        + "\n"
    )


def started_frame(request_id: str) -> dict[str, Any]:
    return {"id": request_id, "event": "started"}


def progress_frame(request_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": request_id, "event": "progress", "data": dict(data)}


def terminal_success_frame(
    request_id: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "result": dict(result)}


def terminal_error_frame(
    request_id: str, *, kind: str, code: str, message: str
) -> dict[str, Any]:
    return {
        "id": request_id,
        "ok": False,
        "error": {"kind": kind, "code": code, "message": message},
    }


def fatal_transport_failure(reason: str) -> None:
    """The ONE fatal-shutdown primitive (Round 7 §1-§4 of the design plan).
    Callable from any thread the instant a protocol write is confirmed to
    have failed. Terminates the ENTIRE process via os._exit() -- not the
    calling thread -- because reader and worker are independent threads
    and a thread-scoped sys.exit() would leave the other, and stdout,
    alive, breaking the invariant Rust's drain-to-EOF recovery model
    depends on. os._exit() bypasses normal interpreter shutdown
    deliberately: nothing further can be reported once stdout is broken,
    and any window in which another thread keeps running is exactly the
    race this primitive exists to close.
    """
    try:
        sys.stderr.write(f"fatal transport failure: {reason}\n")
        sys.stderr.flush()
    except OSError:
        pass
    os._exit(1)
