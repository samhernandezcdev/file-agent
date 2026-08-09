"""Guardrail: persistence writes only land inside the configured app-data root.

Not a copy of FA-002/FA-003's "zero filesystem-mutation calls" guardrail —
persistence legitimately writes a SQLite file. What must be proven instead:
the only filesystem-mutation call anywhere in this package is the one
allow-listed app-data-root mkdir, and a real end-to-end run never touches a
separate "sandbox" tree.
"""

import ast
from collections.abc import Callable
from pathlib import Path

from file_agent.domain import DomainEvent, EntityType, EventType
from file_agent.hasher import HashSuccess
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.scanner import ScanResult

FORBIDDEN_DOTTED_CALLS = {
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("os", "makedirs"),
    ("os", "symlink"),
    ("os", "link"),
    ("os", "chmod"),
    ("os", "chown"),
    ("os", "utime"),
    ("os", "replace"),
    ("os", "truncate"),
    ("shutil", "move"),
    ("shutil", "rmtree"),
}
FORBIDDEN_METHOD_NAMES = {
    "unlink",
    "rename",
    "replace",
    "touch",
    "write_text",
    "write_bytes",
    "write",
    "writelines",
}

PERSISTENCE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "persistence"
)


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


class _MutationVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []
        self.mkdir_calls = 0

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                parts = dotted.split(".")
                if len(parts) >= 2 and (parts[-2], parts[-1]) in FORBIDDEN_DOTTED_CALLS:
                    self.violations.append(f"forbidden call: {dotted}(")
            if func.attr == "mkdir":
                self.mkdir_calls += 1
            elif func.attr in FORBIDDEN_METHOD_NAMES:
                self.violations.append(f"forbidden method call: .{func.attr}(")
        self.generic_visit(node)


def test_only_engine_py_calls_mkdir_and_nothing_else_mutates() -> None:
    persistence_files = sorted(PERSISTENCE_DIR.glob("*.py"))
    assert persistence_files, (
        f"expected persistence source files under {PERSISTENCE_DIR}"
    )

    offenders: list[str] = []
    mkdir_sites: dict[str, int] = {}
    for path in persistence_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)
        if visitor.mkdir_calls:
            mkdir_sites[path.name] = visitor.mkdir_calls

    assert not offenders, f"forbidden filesystem-mutation patterns found: {offenders}"
    assert mkdir_sites == {"engine.py": 1}, (
        f"expected exactly one mkdir call, in engine.py: {mkdir_sites}"
    )


def test_sandbox_tree_untouched_by_full_persistence_run(
    tmp_path: Path,
    make_scan_result: Callable[..., ScanResult],
    make_event: Callable[..., DomainEvent],
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    sandbox_file = sandbox / "important.txt"
    sandbox_file.write_bytes(b"do not touch")
    before = {
        p: (p.read_bytes(), p.stat().st_mtime)
        for p in sandbox.rglob("*")
        if p.is_file()
    }

    app_data_root = tmp_path / "appdata"
    config = AppPaths.from_root(app_data_root)
    engine, session_factory = create_engine_and_session_factory(config)
    Base.metadata.create_all(engine)
    store = FileAgentStore(session_factory)
    try:
        result = make_scan_result(file_count=1)
        store.record_scan(result)
        original = result.files[0]
        hashed = original.with_sha256("a" * 64)
        event = make_event(
            event_type=EventType.FILE_HASHED,
            entity_type=EntityType.FILE,
            entity_id=hashed.id,
            payload={"sha256": hashed.sha256, "path": str(hashed.path)},
        )
        store.record_hash_success(
            HashSuccess(original=original, hashed=hashed, event=event)
        )
    finally:
        engine.dispose()

    after = {
        p: (p.read_bytes(), p.stat().st_mtime)
        for p in sandbox.rglob("*")
        if p.is_file()
    }
    assert after == before

    app_data_entries = {p.name for p in app_data_root.iterdir()}
    assert app_data_entries <= {
        "file-agent.sqlite3",
        "file-agent.sqlite3-wal",
        "file-agent.sqlite3-shm",
    }
