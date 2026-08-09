"""Guardrail: the hasher package must never call filesystem-mutating APIs.

AST-based, same approach as tests/scanner/test_no_filesystem_mutations.py.
This is the first package that legitimately opens file *content* (not just
os.stat/os.scandir), so the write-mode-open() detection is exercised for
real here.
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
    ("os", "replace"),
    ("os", "truncate"),
    ("shutil", "move"),
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
}

FORBIDDEN_IMPORT_NAMES = {
    "remove",
    "unlink",
    "rmdir",
    "mkdir",
    "makedirs",
    "symlink",
    "link",
    "chmod",
    "chown",
    "utime",
    "replace",
    "truncate",
    "move",
    "rmtree",
}

HASHER_DIR = Path(__file__).resolve().parents[2] / "src" / "file_agent" / "hasher"


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
            if func.attr == "open":
                self._check_open_mode(node)
        elif isinstance(func, ast.Name) and func.id == "open":
            self._check_open_mode(node)
        self.generic_visit(node)

    def _check_open_mode(self, node: ast.Call) -> None:
        mode_arg = node.args[1] if len(node.args) >= 2 else None
        for kw in node.keywords:
            if kw.arg == "mode":
                mode_arg = kw.value
        if (
            isinstance(mode_arg, ast.Constant)
            and isinstance(mode_arg.value, str)
            and any(flag in mode_arg.value for flag in ("w", "a", "x", "+"))
        ):
            self.violations.append(
                f"open() with write-capable mode: {mode_arg.value!r}"
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in {"os", "shutil"}:
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORT_NAMES:
                    self.violations.append(
                        f"forbidden import: from {node.module} import {alias.name}"
                    )
        self.generic_visit(node)


def test_no_hasher_source_file_mutates_the_filesystem() -> None:
    hasher_files = sorted(HASHER_DIR.glob("*.py"))
    assert hasher_files, f"expected hasher source files under {HASHER_DIR}"

    offenders: list[str] = []
    for path in hasher_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        for violation in visitor.violations:
            offenders.append(f"{path.name}: {violation}")

    assert not offenders, f"forbidden filesystem-mutation patterns found: {offenders}"
