"""Guardrail: the classifier package must never touch the filesystem at all.

Stronger than FA-002/FA-003's guardrails, which permit reads (the scanner
and hasher legitimately touch disk) and forbid only writes. FA-005 performs
NO filesystem I/O of any kind — not even a stat() — since it classifies
purely from already-in-memory DiscoveredFile fields. This test asserts a
strictly larger forbidden set: any open(), any os.*/os.path.* call, and any
pathlib.Path I/O method, anywhere in src/file_agent/classifier/.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULE_PREFIXES = {"os", "shutil", "io"}

FORBIDDEN_PATH_METHODS = [
    "open",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
    "stat",
    "lstat",
    "exists",
    "is_file",
    "is_dir",
    "is_symlink",
    "iterdir",
    "glob",
    "rglob",
    "resolve",
    "mkdir",
    "rmdir",
    "unlink",
    "rename",
    "replace",
    "touch",
    "scandir",
    "walk",
]

CLASSIFIER_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "classifier"
)


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


class _FilesystemAccessVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in FORBIDDEN_MODULE_PREFIXES:
                self.violations.append(f"forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.split(".")[0] in FORBIDDEN_MODULE_PREFIXES:
            self.violations.append(f"forbidden import: from {node.module} import ...")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "open":
                self.violations.append("forbidden call: open(")
        elif isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                root = dotted.split(".")[0]
                if root in FORBIDDEN_MODULE_PREFIXES:
                    self.violations.append(f"forbidden call: {dotted}(")
            if func.attr in FORBIDDEN_PATH_METHODS:
                self.violations.append(f"forbidden method call: .{func.attr}(")
        self.generic_visit(node)


def test_no_classifier_source_file_touches_the_filesystem() -> None:
    classifier_files = sorted(CLASSIFIER_DIR.glob("*.py"))
    assert classifier_files, f"expected classifier source files under {CLASSIFIER_DIR}"

    offenders: list[str] = []
    for path in classifier_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _FilesystemAccessVisitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)

    assert not offenders, f"forbidden filesystem-access patterns found: {offenders}"
