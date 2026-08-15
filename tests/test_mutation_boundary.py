"""Repo-wide guardrail: no filesystem-mutation primitive may appear anywhere
in src/file_agent/ except managed_fs/operations.py (the sole approved
managed-root mutation call site, shared by TransactionEngine and
RecoveryEngine -- see file_agent.managed_fs), persistence/, and
vault_engine/ -- the latter two each have their own dedicated, stricter
local guardrail already proving their allow-listed mutation call sites are
correctly scoped (see tests/persistence/test_app_data_boundary.py and
tests/vault_engine/test_vault_boundary.py; excluded here to avoid two
guardrails disagreeing about the same allow-listed call).

This is the architectural enforcement of docs/SAFETY.md's core Milestone-2
invariant: "All managed-file filesystem mutation must go through one narrow,
audited boundary." persistence's and vault_engine's own writes are entirely
confined to FileAgent's app-owned storage (the SQLite file; the Vault
directory tree) and never touch a managed/sandbox path -- see their local
guardrails -- so excluding them here does not weaken managed_fs/operations.py's
exclusive authority over managed-ROOT mutation. Neither transaction_engine
nor recovery_engine has any mutation call site of its own: both call
managed_fs's functions as bare function calls (ast.Name, not ast.Attribute),
which this scan does not even need to special-case -- see managed_fs's own
package-local guardrail for the "no open(..., 'wb')" check specific to that
one file.
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

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "file_agent"
APPROVED_MUTATION_FILE = SRC_ROOT / "managed_fs" / "operations.py"
EXCLUDED_DIRS = {SRC_ROOT / "persistence", SRC_ROOT / "vault_engine"}


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


def _is_excluded(path: Path) -> bool:
    return path == APPROVED_MUTATION_FILE or any(
        excluded in path.parents for excluded in EXCLUDED_DIRS
    )


def test_no_source_file_outside_managed_fs_mutates_the_filesystem() -> None:
    source_files = sorted(SRC_ROOT.rglob("*.py"))
    assert source_files, f"expected source files under {SRC_ROOT}"

    checked_files = [path for path in source_files if not _is_excluded(path)]
    assert checked_files, "expected at least one file to actually be checked"

    offenders: list[str] = []
    for path in checked_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        offenders.extend(
            f"{path.relative_to(SRC_ROOT)}: {v}" for v in visitor.violations
        )

    assert not offenders, f"forbidden filesystem-mutation patterns found: {offenders}"


def test_approved_mutation_file_actually_contains_the_mutation_call() -> None:
    """Guards against the guardrail above passing vacuously if the sole
    approved call site is ever accidentally emptied out."""
    tree = ast.parse(
        APPROVED_MUTATION_FILE.read_text(encoding="utf-8"),
        filename=str(APPROVED_MUTATION_FILE),
    )
    visitor = _MutationVisitor()
    visitor.visit(tree)
    assert visitor.violations, (
        f"expected {APPROVED_MUTATION_FILE} to contain a real mutation call, found none"
    )
