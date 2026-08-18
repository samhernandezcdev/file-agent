"""The desktop sidecar process entrypoint: `python -m file_agent.desktop_api`.

Implements FA-017 Round 7's transport lifecycle exactly:
startup handshake (write+flush, fail closed) -> ProtocolWriter + stdout
redirection -> reader thread (parses stdin, enqueues valid requests,
answers malformed ones directly) -> worker thread (FIFO, one command at a
time, STARTED write+flush BEFORE the handler runs) -> any confirmed
protocol-write failure, from either thread, calls
protocol.fatal_transport_failure -- terminating the whole process via
os._exit(), never a thread-scoped sys.exit().

A handler-level bug is NOT a transport failure: it is caught, logged to
stderr, and rendered as a per-request `kind: "fatal"` terminal frame -- the
sidecar keeps running and keeps serving the next queued request.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Any, TextIO

from file_agent.application import FileAgentApplicationService
from file_agent.desktop_api.bootstrap import build_application_service
from file_agent.desktop_api.dispatcher import dispatch
from file_agent.desktop_api.errors import UnknownCommandError
from file_agent.desktop_api.protocol import (
    ProtocolWriter,
    fatal_transport_failure,
    handshake_line,
    started_frame,
    terminal_error_frame,
    terminal_success_frame,
)

_QUEUE_MAX = 64
"""Bounded defensive cap on accepted-but-not-yet-started requests. Purely
a resource guard against a misbehaving/compromised host flooding the
sidecar -- Python's single-worker FIFO is the actual correctness
mechanism, never this number."""

_GENERIC_INTERNAL_ERROR_DETAIL = (
    "No pudimos completar esta acción de forma segura. "
    "No se realizó ningún cambio en este archivo."
)


@dataclass(frozen=True, slots=True)
class _Request:
    id: str
    command: str
    params: dict[str, Any]


def _parse_request_line(line: str) -> _Request:
    data = json.loads(line)
    if not isinstance(data, dict):
        raise TypeError("request frame must be a JSON object")
    request_id = data.get("id")
    command = data.get("command")
    params = data.get("params", {})
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("missing/invalid 'id'")
    if not isinstance(command, str) or not command:
        raise ValueError("missing/invalid 'command'")
    if not isinstance(params, dict):
        raise TypeError("'params' must be an object")
    return _Request(id=request_id, command=command, params=params)


def _recover_request_id(line: str) -> str | None:
    """Best-effort id recovery for a line that failed to parse as a
    well-formed request -- used only to decide whether a malformed-request
    response can be addressed to a specific id at all. Never raises."""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        candidate = data.get("id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _reader_loop(
    stdin: TextIO,
    work_queue: queue.Queue[_Request | None],
    writer: ProtocolWriter,
) -> None:
    """Malformed input never enters the execution queue. Rust is the only
    writer to this process's stdin, so malformed input represents a
    protocol/programming error, not normal user behavior."""
    for raw_line in stdin:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        try:
            request = _parse_request_line(line)
        except (ValueError, TypeError) as exc:
            recovered_id = _recover_request_id(line)
            if recovered_id is None:
                sys.stderr.write(f"malformed request, no id recoverable: {exc}\n")
                sys.stderr.flush()
                continue
            try:
                writer.emit_frame(
                    terminal_error_frame(
                        recovered_id,
                        kind="malformed_request",
                        code="malformed_request",
                        message=str(exc),
                    )
                )
            except OSError as write_exc:
                fatal_transport_failure(
                    f"reader malformed-request emit failed: {write_exc}"
                )
                return  # unreachable -- os._exit already terminated the process
            continue

        if work_queue.qsize() >= _QUEUE_MAX:
            try:
                writer.emit_frame(
                    terminal_error_frame(
                        request.id,
                        kind="busy",
                        code="queue_full",
                        message=(
                            "FileAgent está ocupado en este momento. "
                            "Inténtalo de nuevo en unos segundos."
                        ),
                    )
                )
            except OSError as write_exc:
                fatal_transport_failure(f"reader queue-full emit failed: {write_exc}")
                return
            continue

        work_queue.put(request)
    work_queue.put(None)  # stdin EOF -- tell the worker loop to stop cleanly


def _worker_loop(
    work_queue: queue.Queue[_Request | None],
    writer: ProtocolWriter,
    service: FileAgentApplicationService,
) -> None:
    """Exactly one FileAgent command executes at a time -- a plain FIFO
    queue, not a permission system. Request ids are transport correlation
    only; they never grant concurrent-execution authority."""
    while True:
        request = work_queue.get()
        if request is None:
            return

        try:
            writer.emit_frame(started_frame(request.id))
        except OSError as exc:
            fatal_transport_failure(f"started emit failed for {request.id}: {exc}")
            return  # unreachable

        try:
            outcome = dispatch(request.command, request.params, service)
        except UnknownCommandError as exc:
            frame = terminal_error_frame(
                request.id, kind="fatal", code="unknown_command", message=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 -- a genuine handler bug, not a
            # transport failure: this one request fails, the sidecar process
            # keeps running. The real exception is logged to stderr only.
            sys.stderr.write(f"unexpected error handling {request.command}: {exc!r}\n")
            sys.stderr.flush()
            frame = terminal_error_frame(
                request.id,
                kind="fatal",
                code="internal_error",
                message=_GENERIC_INTERNAL_ERROR_DETAIL,
            )
        else:
            if outcome.ok:
                assert outcome.result is not None
                frame = terminal_success_frame(request.id, outcome.result)
            else:
                assert outcome.error_kind is not None
                assert outcome.error_code is not None
                assert outcome.error_message is not None
                frame = terminal_error_frame(
                    request.id,
                    kind=outcome.error_kind,
                    code=outcome.error_code,
                    message=outcome.error_message,
                )

        try:
            writer.emit_frame(frame)
        except OSError as exc:
            fatal_transport_failure(f"terminal emit failed for {request.id}: {exc}")
            return  # unreachable


def main() -> None:
    real_stdout = sys.stdout
    try:
        real_stdout.write(handshake_line())
        real_stdout.flush()
    except OSError as exc:
        # No reader/worker thread exists yet; ProtocolWriter does not exist
        # yet either -- terminate startup via the same process-wide
        # primitive every other fatal path uses.
        fatal_transport_failure(f"handshake write/flush failed: {exc}")
        return  # unreachable

    writer = ProtocolWriter(real_stdout)
    sys.stdout = sys.stderr  # defense-in-depth; see protocol.py's docstring
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    service, engine = build_application_service()

    work_queue: queue.Queue[_Request | None] = queue.Queue()
    reader = threading.Thread(
        target=_reader_loop, args=(sys.stdin, work_queue, writer), daemon=True
    )
    worker = threading.Thread(
        target=_worker_loop, args=(work_queue, writer, service), daemon=True
    )
    reader.start()
    worker.start()
    reader.join()
    worker.join()
    engine.dispose()


if __name__ == "__main__":
    main()
