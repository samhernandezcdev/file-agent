"""Structural guardrails, mirroring tests/application/
test_managed_root_ast_guardrail.py's own established pattern (AST-walk a
package, fail the build on a forbidden call/import shape) --
desktop_api/'s specific trust-boundary and stdout-discipline invariants:

1. desktop_api never imports file_agent.managed_fs, and never imports the
   internal engine classes it must not construct directly
   (TransactionEngine, RecoveryEngine, ExecutionAuthorization,
   SandboxRoot).
2. No production module under desktop_api/ writes to stdout by any path
   other than ProtocolWriter.emit_frame -- no bare print(), no
   sys.stdout.write(), anywhere outside protocol.py's own ProtocolWriter
   class and __main__.py's one sanctioned pre-handshake handshake write.
"""

from __future__ import annotations

import ast
from pathlib import Path

DESKTOP_API_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "desktop_api"
)

_FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "file_agent.managed_fs",
        "file_agent.transaction_engine",
        "file_agent.recovery_engine",
    }
)

_FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "SandboxRoot",
        "ExecutionAuthorization",
        "TransactionEngine",
        "RecoveryEngine",
        "TransactionRequest",
        "HumanReviewDecision",
    }
)

# managed_roots.py's _resolve_safe_managed_root itself legitimately imports
# SandboxRoot -- desktop_api never imports that module directly at all
# (it only calls FileAgentApplicationService's public methods), so no
# per-file allowlist is needed here, unlike application/'s own guardrail.


def _source_files() -> list[Path]:
    return sorted(DESKTOP_API_DIR.glob("*.py"))


def test_no_forbidden_module_imports() -> None:
    offenders: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module in _FORBIDDEN_IMPORT_MODULES
                    or any(
                        node.module.startswith(f"{m}.")
                        for m in _FORBIDDEN_IMPORT_MODULES
                    )
                )
            ):
                offenders.append(
                    f"{path.name}:{node.lineno}: import from {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_IMPORT_MODULES:
                        offenders.append(
                            f"{path.name}:{node.lineno}: import {alias.name}"
                        )
    assert not offenders, (
        "desktop_api/ must call FileAgentApplicationService's public API only "
        f"-- never these engine internals directly: {offenders}"
    )


def test_no_forbidden_symbol_imports() -> None:
    offenders: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_IMPORT_NAMES:
                        offenders.append(
                            f"{path.name}:{node.lineno}: import {alias.name}"
                        )
    assert not offenders, (
        "desktop_api/ must never construct these trust-boundary internals "
        f"directly: {offenders}"
    )


def _is_print_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def _is_sys_stdout_write(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "stdout"
    )


def test_no_direct_stdout_writes_outside_protocol_writer_and_handshake() -> None:
    """print()/sys.stdout.write() must never appear in desktop_api/
    production code except inside protocol.py's ProtocolWriter.emit_frame
    (the sole sanctioned writer) and __main__.py's own pre-handshake
    `real_stdout.write` line (captured before any redirection, and before
    ProtocolWriter exists at all -- see protocol.py/Round 7 §5)."""
    allowed = {
        ("protocol.py", "ProtocolWriter"),
    }
    offenders: list[str] = []

    def visit(node: ast.AST, enclosing_class: str | None, file_name: str) -> None:
        current = enclosing_class
        if isinstance(node, ast.ClassDef):
            current = node.name
        if (_is_print_call(node) or _is_sys_stdout_write(node)) and (
            file_name,
            current,
        ) not in allowed:
            offenders.append(f"{file_name}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child, current, file_name)

    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visit(tree, None, path.name)

    # __main__.py's handshake write targets a locally-bound `real_stdout`
    # variable, not `sys.stdout`/print -- it never matches the patterns
    # above, so no explicit allowlist entry is needed for it.
    assert not offenders, (
        "direct stdout writes outside ProtocolWriter.emit_frame are forbidden "
        f"in desktop_api/ production code: {offenders}"
    )
