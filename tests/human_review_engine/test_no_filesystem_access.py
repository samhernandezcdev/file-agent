"""Guardrail: the human_review_engine package must never touch the
filesystem. Same strict shape as classifier/proposal_engine/policy_engine's
guardrails -- review recording is a pure, total function over two
already-in-memory objects, so NO filesystem I/O of any kind is expected.
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

HUMAN_REVIEW_ENGINE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "human_review_engine"
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


def test_no_human_review_engine_source_file_touches_the_filesystem() -> None:
    source_files = sorted(HUMAN_REVIEW_ENGINE_DIR.glob("*.py"))
    assert source_files, (
        f"expected human_review_engine source files under {HUMAN_REVIEW_ENGINE_DIR}"
    )

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _FilesystemAccessVisitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)

    assert not offenders, f"forbidden filesystem-access patterns found: {offenders}"
