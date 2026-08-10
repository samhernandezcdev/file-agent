"""Guardrail: the policy_engine package must never touch the filesystem.

Same strict shape as the classifier's (FA-005) and proposal_engine's (FA-006)
guardrails — policy evaluation is a pure, total function over an
already-in-memory FileProposal, so NO filesystem I/O of any kind is
expected: any open(), any os.*/shutil.*/io.* call, and any pathlib.Path I/O
method, anywhere in src/file_agent/policy_engine/.
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

POLICY_ENGINE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "policy_engine"
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


def test_no_policy_engine_source_file_touches_the_filesystem() -> None:
    source_files = sorted(POLICY_ENGINE_DIR.glob("*.py"))
    assert source_files, (
        f"expected policy_engine source files under {POLICY_ENGINE_DIR}"
    )

    offenders: list[str] = []
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _FilesystemAccessVisitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)

    assert not offenders, f"forbidden filesystem-access patterns found: {offenders}"
