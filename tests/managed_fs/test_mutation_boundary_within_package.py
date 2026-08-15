"""Guardrail: within managed_fs, only operations.py may call a filesystem
mutation primitive -- and within operations.py itself, open(..., "wb") is
banned as a managed-root file-creation primitive (exclusive "xb" creation
is the only approved mode). Mirrors transaction_engine's former package-local
guardrail (now removed -- transaction_engine has zero mutation call sites of
its own after the FA-011 refactor, same as recovery_engine)."""

import ast
from pathlib import Path

import pytest

from file_agent.managed_fs import move_no_replace, write_new_file

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
    "replace",
    "mkdir",
    "touch",
    "write_text",
    "write_bytes",
}
""""rename" deliberately excluded -- it's the approved primitive inside
operations.py itself, counted separately below."""

MANAGED_FS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "file_agent" / "managed_fs"
)
APPROVED_MUTATION_FILE = "operations.py"
BANNED_OPEN_MODE = "wb"


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
        self.rename_calls = 0
        self.open_modes: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                parts = dotted.split(".")
                if len(parts) >= 2 and (parts[-2], parts[-1]) in FORBIDDEN_DOTTED_CALLS:
                    self.violations.append(f"forbidden call: {dotted}(")
                if func.attr == "rename":
                    self.rename_calls += 1
                elif func.attr in FORBIDDEN_METHOD_NAMES:
                    self.violations.append(f"forbidden method call: .{func.attr}(")
        elif isinstance(func, ast.Name) and func.id == "open":
            args = node.args
            if (
                len(args) >= 2
                and isinstance(args[1], ast.Constant)
                and isinstance(args[1].value, str)
            ):
                self.open_modes.append(args[1].value)
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    self.open_modes.append(str(keyword.value.value))
        self.generic_visit(node)


def test_only_operations_py_calls_a_mutation_primitive() -> None:
    source_files = sorted(MANAGED_FS_DIR.glob("*.py"))
    assert source_files, f"expected managed_fs source files under {MANAGED_FS_DIR}"

    offenders: list[str] = []
    mutating_files: set[str] = set()
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _MutationVisitor()
        visitor.visit(tree)
        if visitor.violations or visitor.rename_calls:
            mutating_files.add(path.name)
        if path.name != APPROVED_MUTATION_FILE:
            offenders.extend(f"{path.name}: {v}" for v in visitor.violations)
            if visitor.rename_calls:
                offenders.append(f"{path.name}: unexpected .rename( call")

    assert not offenders, (
        f"forbidden filesystem-mutation patterns found outside {APPROVED_MUTATION_FILE}: {offenders}"
    )
    assert APPROVED_MUTATION_FILE in mutating_files, (
        f"expected {APPROVED_MUTATION_FILE} to contain the mutation call, found none"
    )


def test_operations_py_never_opens_in_truncating_write_mode() -> None:
    """open(..., "wb") is banned throughout operations.py -- exclusive "xb"
    creation is the only approved managed-root file-creation primitive.
    Catches both positional and keyword mode arguments."""
    path = MANAGED_FS_DIR / "operations.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _MutationVisitor()
    visitor.visit(tree)

    assert BANNED_OPEN_MODE not in visitor.open_modes, (
        f"operations.py must never open(..., {BANNED_OPEN_MODE!r}) -- found modes: "
        f"{visitor.open_modes}"
    )
    assert "xb" in visitor.open_modes, (
        "expected write_new_file to use exclusive creation (open(..., 'xb'))"
    )


def test_write_new_file_uses_exclusive_creation_and_never_overwrites(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing.txt"
    target.write_bytes(b"pre-existing bytes, must survive")

    with pytest.raises(FileExistsError):
        write_new_file(target, [b"attempted overwrite"])

    assert target.read_bytes() == b"pre-existing bytes, must survive"


def test_write_new_file_creates_fresh_path_with_given_bytes(tmp_path: Path) -> None:
    target = tmp_path / "fresh.txt"

    written = write_new_file(target, [b"hello ", b"world"])

    assert written == 11
    assert target.read_bytes() == b"hello world"


def test_move_no_replace_never_overwrites_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"source content")
    destination = tmp_path / "destination.txt"
    destination.write_bytes(b"pre-existing destination content")

    with pytest.raises(OSError):
        move_no_replace(source, destination)

    assert destination.read_bytes() == b"pre-existing destination content"
    assert source.exists()


def test_move_no_replace_relocates_to_a_fresh_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"relocate me")
    destination = tmp_path / "destination.txt"

    move_no_replace(source, destination)

    assert not source.exists()
    assert destination.read_bytes() == b"relocate me"
