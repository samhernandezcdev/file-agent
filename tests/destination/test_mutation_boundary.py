"""Guardrail: file_agent.destination performs zero filesystem mutation and
never imports file_agent.managed_fs. It is a shared, read-only utility
package consumed by both application/ (preview) and transaction_engine/
(execution) -- neither of those relationships is safe unless this package
itself can never mutate anything."""

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
    "write",
    "writelines",
    "symlink_to",
    "hardlink_to",
    "rmdir",
    "chmod",
}

DESTINATION_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "destination"
)


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


class _Visitor(ast.NodeVisitor):
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

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "file_agent.managed_fs" or alias.name.startswith(
                "file_agent.managed_fs."
            ):
                self.violations.append(f"forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "file_agent.managed_fs" or (
            node.module is not None and node.module.startswith("file_agent.managed_fs.")
        ):
            self.violations.append(f"forbidden import: from {node.module} import ...")
        self.generic_visit(node)


def test_destination_has_no_mutation_primitives_and_no_managed_fs_import() -> None:
    source_files = sorted(DESTINATION_DIR.glob("*.py"))
    assert source_files, f"expected destination source files under {DESTINATION_DIR}"

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)

    assert not offenders, f"forbidden patterns found in destination/: {offenders}"
