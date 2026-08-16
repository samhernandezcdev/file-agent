"""inspect_destination -- the single, shared, read-only destination-safety
check both OrganizationPlanner and TransactionEngine call.

Round-3 correction 2: DestinationConflict explicitly includes
BASENAME_MISMATCH. Round-3 correction 3: only OSError-class observation
failures become OBSERVATION_FAILED; programming/configuration errors
(ValueError, KeyError, ...) must propagate uncaught.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.destination.inspection import (
    DestinationConflict,
    inspect_destination,
)
from file_agent.scanner import SandboxRoot


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


def test_no_conflict_for_a_clean_destination(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "report.txt"

    result = inspect_destination(sandbox_root, source, destination)

    assert result.conflict is DestinationConflict.NONE
    assert result.destination_path == destination


def test_source_equals_destination(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    already_placed = sandbox_root.path / "Documents" / "report.txt"
    already_placed.write_bytes(b"hello")

    result = inspect_destination(sandbox_root, already_placed, already_placed)

    assert result.conflict is DestinationConflict.SOURCE_EQUALS_DESTINATION


def test_basename_mismatch(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    """Round-3 correction 2: DestinationConflict.BASENAME_MISMATCH exists
    and is produced when source/destination filenames differ."""
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "renamed.txt"

    result = inspect_destination(sandbox_root, source, destination)

    assert result.conflict is DestinationConflict.BASENAME_MISMATCH


def test_destination_outside_sandbox(
    tmp_path: Path, sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    source = make_source_file("report.txt")
    outside = tmp_path / "outside" / "report.txt"
    outside.parent.mkdir()

    result = inspect_destination(sandbox_root, source, outside)

    assert result.conflict is DestinationConflict.OUTSIDE_SANDBOX


def test_unsafe_reparse_point_ancestor(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    """An in-bounds junction (pointing at another directory still inside the
    sandbox) is still rejected -- containment alone would pass, but no
    reparse point may sit anywhere between the sandbox root and the
    destination's parent (mirrors TransactionEngine's own established
    conservative stance, now shared via this one function)."""
    source = make_source_file("report.txt")
    real_docs = sandbox_root.path / "RealDocs"
    real_docs.mkdir()
    documents = sandbox_root.path / "Documents"
    documents.rmdir()
    _make_junction(documents, real_docs)

    result = inspect_destination(sandbox_root, source, documents / "report.txt")

    assert result.conflict is DestinationConflict.UNSAFE_REPARSE_POINT


def test_escaping_junction_resolves_outside_sandbox(
    tmp_path: Path, sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    """A junction pointing OUTSIDE the sandbox is followed by containment
    resolution and correctly classified as OUTSIDE_SANDBOX, not
    UNSAFE_REPARSE_POINT -- containment is checked before the ancestor
    reparse-safety walk, exactly reproducing TransactionEngine's own prior
    behavior for this scenario."""
    source = make_source_file("report.txt")
    outside_target = tmp_path / "outside_documents"
    outside_target.mkdir()
    documents = sandbox_root.path / "Documents"
    documents.rmdir()
    _make_junction(documents, outside_target)

    result = inspect_destination(sandbox_root, source, documents / "report.txt")

    assert result.conflict is DestinationConflict.OUTSIDE_SANDBOX


def test_destination_parent_missing(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    source = make_source_file("report.txt")
    (sandbox_root.path / "Documents").rmdir()

    result = inspect_destination(
        sandbox_root, source, sandbox_root.path / "Documents" / "report.txt"
    )

    assert result.conflict is DestinationConflict.PARENT_MISSING


def test_destination_already_occupied(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "report.txt"
    destination.write_bytes(b"already here")

    result = inspect_destination(sandbox_root, source, destination)

    assert result.conflict is DestinationConflict.ALREADY_OCCUPIED


def test_dangling_symlink_at_destination_counts_as_occupied(
    sandbox_root: SandboxRoot, make_source_file: Callable[..., Path]
) -> None:
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "report.txt"
    nonexistent_target = sandbox_root.path / "does_not_exist.txt"
    try:
        destination.symlink_to(nonexistent_target)
    except OSError:
        pytest.skip("symlink creation requires elevated privileges on this system")

    result = inspect_destination(sandbox_root, source, destination)

    assert result.conflict is DestinationConflict.ALREADY_OCCUPIED


def test_observation_failed_on_os_error(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-3 correction 3: only OSError-class failures become
    OBSERVATION_FAILED."""
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "report.txt"

    def _raise_permission_error(self: Path) -> bool:
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(Path, "exists", _raise_permission_error)

    result = inspect_destination(sandbox_root, source, destination)

    assert result.conflict is DestinationConflict.OBSERVATION_FAILED


def test_non_os_error_propagates_uncaught(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-3 correction 3: a programming/configuration error must never be
    converted into OBSERVATION_FAILED -- it propagates exactly as any
    uncaught exception would anywhere else in this codebase."""
    source = make_source_file("report.txt")
    destination = sandbox_root.path / "Documents" / "report.txt"

    def _raise_value_error(self: Path) -> bool:
        raise ValueError("simulated programming error, not a filesystem problem")

    monkeypatch.setattr(Path, "exists", _raise_value_error)

    with pytest.raises(ValueError, match="simulated programming error"):
        inspect_destination(sandbox_root, source, destination)
