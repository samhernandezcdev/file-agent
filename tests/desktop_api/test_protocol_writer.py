"""ProtocolWriter unit tests: exact handshake framing, and the single-
writer serialization guarantee (Round 5/7 §"SOLE PROTOCOL WRITER") -- many
threads hammering emit_frame concurrently must never interleave bytes;
every line written must be one complete, independently-parseable JSON
object."""

from __future__ import annotations

import io
import json
import threading

from file_agent.desktop_api.protocol import (
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    ProtocolWriter,
    handshake_line,
    progress_frame,
    started_frame,
    terminal_error_frame,
    terminal_success_frame,
)


def test_handshake_line_is_exact_and_single_line() -> None:
    line = handshake_line()
    assert line.endswith("\n")
    assert line.count("\n") == 1
    payload = json.loads(line)
    assert payload == {"protocol": PROTOCOL_NAME, "protocol_version": PROTOCOL_VERSION}


def test_frame_builders_produce_expected_shapes() -> None:
    assert started_frame("x") == {"id": "x", "event": "started"}
    assert progress_frame("x", {"n": 1}) == {
        "id": "x",
        "event": "progress",
        "data": {"n": 1},
    }
    assert terminal_success_frame("x", {"a": 1}) == {
        "id": "x",
        "ok": True,
        "result": {"a": 1},
    }
    error = terminal_error_frame("x", kind="fatal", code="c", message="m")
    assert error == {
        "id": "x",
        "ok": False,
        "error": {"kind": "fatal", "code": "c", "message": "m"},
    }


def test_emit_frame_writes_complete_newline_terminated_json() -> None:
    stream = io.StringIO()
    writer = ProtocolWriter(stream)
    writer.emit_frame({"id": "1", "event": "started"})
    writer.emit_frame({"id": "1", "ok": True, "result": {}})
    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"id": "1", "event": "started"}
    assert json.loads(lines[1]) == {"id": "1", "ok": True, "result": {}}


def test_concurrent_emit_frame_never_interleaves_bytes() -> None:
    """Many threads write many frames concurrently through ONE
    ProtocolWriter -- every resulting line must independently parse as
    complete JSON. A broken lock would produce a line that is neither
    valid JSON nor attributable to any single emit_frame call."""
    stream = io.StringIO()
    writer = ProtocolWriter(stream)
    frames_per_thread = 200
    thread_count = 8

    def _hammer(thread_index: int) -> None:
        for i in range(frames_per_thread):
            writer.emit_frame(
                {"id": f"t{thread_index}-{i}", "event": "progress", "data": {"i": i}}
            )

    threads = [threading.Thread(target=_hammer, args=(t,)) for t in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = stream.getvalue().splitlines()
    assert len(lines) == frames_per_thread * thread_count
    seen_ids: set[str] = set()
    for line in lines:
        payload = json.loads(line)  # raises if any line is corrupted/interleaved
        assert payload["id"] not in seen_ids
        seen_ids.add(payload["id"])
    assert len(seen_ids) == frames_per_thread * thread_count
