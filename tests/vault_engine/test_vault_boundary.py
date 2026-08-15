"""Local, stricter guardrail for vault_engine -- mirrors
tests/persistence/test_app_data_boundary.py's shape. vault_engine is
excluded from the repo-wide tests/test_mutation_boundary.py guardrail (see
that file's EXCLUDED_DIRS/docstring) precisely because it needs this
package-local, more permissive-but-still-exact allow-list instead: unlike
every other engine package, vault_engine legitimately performs several kinds
of filesystem mutation (mkdir, chunked write, rename, unlink), all confined
to FileAgent's app-owned Vault tree.

What must be proven: every mutation call site anywhere in vault_engine is
one of a known, allow-listed set at a known location -- not just "no
forbidden dotted os.*/shutil.* calls", which is what the repo-wide guardrail
already checks and which this file also re-checks locally for belt-and-
suspenders coverage.
"""

import ast
import subprocess
from collections.abc import Callable
from pathlib import Path

from file_agent.domain import (
    VaultCaptureRequest,
    VaultCaptureStatus,
    VaultRejectionCode,
)
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import VaultEngine

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
    ("os", "truncate"),
    ("shutil", "move"),
    ("shutil", "copy"),
    ("shutil", "copy2"),
    ("shutil", "copyfile"),
    ("shutil", "copytree"),
    ("shutil", "rmtree"),
}
"""os.rename/os.replace deliberately excluded here -- unlike everywhere
else in this codebase, vault_engine's own publish step uses the bare
Path.rename() *method* (counted separately below), and nothing in this
package calls the module-level os.rename/os.replace functions directly."""

MUTATION_METHOD_NAMES = {
    "mkdir",
    "rmdir",
    "unlink",
    "rename",
    "replace",
    "touch",
    "write_text",
    "write_bytes",
    "write",
    "writelines",
    "symlink_to",
}
"""The full candidate set of mutation-shaped method names to scan for --
deliberately includes "write"/"writelines" (missing from the repo-wide
guardrail's FORBIDDEN_METHOD_NAMES) since vault_engine is exactly the
package that gap matters for."""

EXPECTED_MUTATION_SITES: dict[str, dict[str, int]] = {
    "storage.py": {"mkdir": 1},
    "engine.py": {"mkdir": 1, "write": 1, "rename": 1, "unlink": 1},
}
"""Every other file in the package must have zero mutation-method calls.
"replace" never appears anywhere -- publish uses .rename( specifically for
its non-overwrite guarantee (see the design plan's Publication primitive
section); a stray .replace( call would silently reintroduce the overwrite
race this design deliberately avoids."""

VAULT_ENGINE_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "vault_engine"
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
        self.method_counts: dict[str, int] = {}

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                parts = dotted.split(".")
                if len(parts) >= 2 and (parts[-2], parts[-1]) in FORBIDDEN_DOTTED_CALLS:
                    self.violations.append(f"forbidden call: {dotted}(")
            if func.attr in MUTATION_METHOD_NAMES:
                self.method_counts[func.attr] = self.method_counts.get(func.attr, 0) + 1
        self.generic_visit(node)


def test_mutation_call_sites_match_the_exact_allow_list() -> None:
    source_files = sorted(VAULT_ENGINE_DIR.glob("*.py"))
    assert source_files, f"expected vault_engine source files under {VAULT_ENGINE_DIR}"

    offenders: list[str] = []
    actual_sites: dict[str, dict[str, int]] = {}
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        offenders.extend(f"{path.name}: {v}" for v in visitor.violations)
        if visitor.method_counts:
            actual_sites[path.name] = visitor.method_counts

    assert not offenders, f"forbidden filesystem-mutation patterns found: {offenders}"
    assert actual_sites == EXPECTED_MUTATION_SITES, (
        f"vault_engine mutation call sites drifted from the allow-list: "
        f"expected {EXPECTED_MUTATION_SITES}, found {actual_sites}"
    )


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_sandbox_tree_untouched_by_full_vault_capture_run(
    tmp_path: Path,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
) -> None:
    source = make_source_file("report.txt", content=b"hello vault")
    before = {
        p: (p.read_bytes(), p.stat().st_mtime)
        for p in sandbox_root.path.rglob("*")
        if p.is_file()
    }

    request = make_request(source, content=b"hello vault")
    engine = VaultEngine(sandbox_root, app_paths)
    result = engine.capture(request)
    assert result.status is VaultCaptureStatus.CAPTURED

    after = {
        p: (p.read_bytes(), p.stat().st_mtime)
        for p in sandbox_root.path.rglob("*")
        if p.is_file()
    }
    assert after == before

    app_data_entries = {p.name for p in app_paths.root.iterdir()}
    assert app_data_entries == {"vault"}


def test_no_write_escapes_app_owned_storage(
    tmp_path: Path,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
) -> None:
    """A Vault objects/<prefix> directory pre-replaced by a junction
    pointing at a third, unrelated directory must never receive a write --
    capture() must reject before ever opening the temp file for that prefix."""
    source = make_source_file("report.txt", content=b"escape me")
    request = make_request(source, content=b"escape me")

    engine = VaultEngine(sandbox_root, app_paths)

    from file_agent.vault_engine.paths import object_prefix_dir

    prefix_dir = object_prefix_dir(app_paths, request.expected_sha256)
    prefix_dir.parent.mkdir(parents=True, exist_ok=True)
    escape_target = tmp_path / "escape_target"
    escape_target.mkdir()
    _make_junction(prefix_dir, escape_target)

    result = engine.capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.VAULT_STORAGE_UNSAFE
    assert list(escape_target.iterdir()) == []
