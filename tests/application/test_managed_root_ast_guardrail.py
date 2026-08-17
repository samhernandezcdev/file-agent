"""FA-015 structural guardrail: application/ never converts a persisted
ManagedRoot.path into an operational SandboxRoot via a direct
SandboxRoot.from_path(...) call, anywhere except inside
_resolve_safe_managed_root's own implementation (managed_roots.py).

Registration-time validation only proves a path was safe ONCE (see that
function's own docstring) -- every service/planner/history/recovery
orchestration call site MUST re-derive the proof fresh, via
_resolve_safe_managed_root, on every use. A future accidental
SandboxRoot.from_path(row.path) anywhere else in application/ would silently
reintroduce the exact live-authority-bypass FA-015 exists to close, so this
guardrail fails the build immediately if one appears -- it is not merely a
style convention.

SandboxRoot.from_path is legitimately unrelated to ManagedRoot in other
packages (the engine layer, tests) and is untouched by this guardrail --
scope is strictly application/*.py."""

import ast
from pathlib import Path

APPLICATION_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "application"
)

_ALLOWED_FILE = "managed_roots.py"
_ALLOWED_FUNCTION = "_resolve_safe_managed_root"


def _is_sandbox_root_from_path_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_path"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "SandboxRoot"
    )


def _offending_calls_outside_allowed_function(tree: ast.Module) -> list[int]:
    """Walks the module, tracking which (if any) enclosing function each node
    is nested in, and returns line numbers of every SandboxRoot.from_path(...)
    call NOT nested inside a function named _ALLOWED_FUNCTION."""
    offenders: list[int] = []

    def visit(node: ast.AST, enclosing_function: str | None) -> None:
        current = enclosing_function
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            current = node.name
        if _is_sandbox_root_from_path_call(node) and current != _ALLOWED_FUNCTION:
            offenders.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree, None)
    return offenders


def test_no_bare_sandbox_root_from_path_outside_resolve_safe_managed_root() -> None:
    source_files = sorted(APPLICATION_DIR.glob("*.py"))
    assert source_files, f"expected application source files under {APPLICATION_DIR}"

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        allowed_file = path.name == _ALLOWED_FILE
        for lineno in _offending_calls_outside_allowed_function(tree):
            if allowed_file:
                offenders.append(
                    f"{path.name}:{lineno}: SandboxRoot.from_path( outside "
                    f"{_ALLOWED_FUNCTION}"
                )
            else:
                offenders.append(f"{path.name}:{lineno}: SandboxRoot.from_path(")

    assert not offenders, (
        "SandboxRoot.from_path(...) must only appear inside "
        f"managed_roots.py's own {_ALLOWED_FUNCTION} -- every other call site "
        "must go through _resolve_safe_managed_root so registration-time "
        "safety is re-proven live on every use. Offending call sites: "
        f"{offenders}"
    )


def test_resolve_safe_managed_root_still_calls_sandbox_root_from_path() -> None:
    """Sanity check against a vacuous guardrail: if a future refactor removes
    the SandboxRoot.from_path call from _resolve_safe_managed_root entirely
    (e.g. routes through a new helper), this test fails loudly rather than
    letting the guardrail above silently stop testing anything real."""
    managed_roots_path = APPLICATION_DIR / _ALLOWED_FILE
    tree = ast.parse(
        managed_roots_path.read_text(encoding="utf-8"), filename=str(managed_roots_path)
    )

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == _ALLOWED_FUNCTION:
            found = any(
                _is_sandbox_root_from_path_call(child) for child in ast.walk(node)
            )
            break

    assert found, (
        f"{_ALLOWED_FUNCTION} in {_ALLOWED_FILE} no longer calls "
        "SandboxRoot.from_path(...) -- update this guardrail's assumptions"
    )
