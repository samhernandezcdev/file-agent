"""Guardrail: within transaction_engine itself, only operations.py may call
a filesystem mutation primitive. Mirrors persistence's own "exactly one
file may mutate" guardrail (test_app_data_boundary.py), applied here to the
package that is the codebase's sole approved mutation boundary.
"""

import ast
from pathlib import Path

FORBIDDEN_DOTTED_CALLS = {
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("os", "mkdir"),
    ("os", "makedirs"),
    ("os", "symlink"),
    ("os", "link"),
    ("os", "chmod"),
    ("os", "chown"),
    ("os", "utime"),
    ("os", "rename"),
    ("os", "replace"),
    ("os", "truncate"),
    ("shutil", "move"),
    ("shutil", "copy"),
    ("shutil", "copy2"),
    ("shutil", "copyfile"),
    ("shutil", "copytree"),
    ("shutil", "rmtree"),
}

FORBIDDEN_METHOD_NAMES = {
    "unlink",
    "rename",
    "replace",
    "mkdir",
    "touch",
    "write_text",
    "write_bytes",
}

TRANSACTION_ENGINE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "transaction_engine"
)
APPROVED_MUTATION_FILE = "operations.py"


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

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                parts = dotted.split(".")
                if len(parts) >= 2 and (parts[-2], parts[-1]) in FORBIDDEN_DOTTED_CALLS:
                    self.violations.append(f"forbidden call: {dotted}(")
                if func.attr in FORBIDDEN_METHOD_NAMES:
                    self.violations.append(f"forbidden method call: .{func.attr}(")
        self.generic_visit(node)


def test_only_operations_py_calls_a_mutation_primitive() -> None:
    source_files = sorted(TRANSACTION_ENGINE_DIR.glob("*.py"))
    assert source_files, (
        f"expected transaction_engine source files under {TRANSACTION_ENGINE_DIR}"
    )

    offenders: list[str] = []
    mutating_files: set[str] = set()
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        if visitor.violations:
            mutating_files.add(path.name)
        if path.name != APPROVED_MUTATION_FILE:
            offenders.extend(f"{path.name}: {v}" for v in visitor.violations)

    assert not offenders, (
        f"forbidden filesystem-mutation patterns found outside {APPROVED_MUTATION_FILE}: {offenders}"
    )
    assert APPROVED_MUTATION_FILE in mutating_files, (
        f"expected {APPROVED_MUTATION_FILE} to contain the mutation call, found none"
    )
