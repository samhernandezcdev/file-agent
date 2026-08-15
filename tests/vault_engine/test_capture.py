"""Core VaultEngine.capture() behavior: success, verification, idempotency,
corruption detection, source-safety rejections, and temp-file cleanup."""

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from file_agent.domain import (
    VaultCaptureRequest,
    VaultCaptureResult,
    VaultCaptureStatus,
    VaultRejectionCode,
)
from file_agent.hasher import FileHasher
from file_agent.persistence import AppPaths
from file_agent.scanner import SandboxRoot
from file_agent.vault_engine import VaultEngine
from file_agent.vault_engine.paths import object_abs_path, tmp_dir


def test_successful_capture_publishes_verified_object(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    content = b"hello vault"
    source = make_source_file("report.txt", content=content)
    request = make_request(source, content=content)

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.CAPTURED
    assert result.verified_sha256 == hashlib.sha256(content).hexdigest()
    assert result.verified_size == len(content)
    assert (
        result.vault_object_path
        == f"objects/{result.verified_sha256[:2]}/{result.verified_sha256}"
    )
    final_path = object_abs_path(app_paths, result.verified_sha256)
    assert final_path.exists()
    assert final_path.read_bytes() == content


def test_published_object_is_byte_for_byte_identical(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    content = bytes(range(256)) * 1024  # multi-chunk content
    source = make_source_file("blob.bin", content=content)
    request = make_request(source, content=content)

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.CAPTURED
    final_path = object_abs_path(app_paths, result.verified_sha256)  # type: ignore[arg-type]
    assert final_path.read_bytes() == content
    assert hashlib.sha256(final_path.read_bytes()).hexdigest() == result.verified_sha256


def test_source_file_unchanged_after_capture(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    content = b"do not touch me"
    source = make_source_file("keepsafe.txt", content=content)
    before = (source.read_bytes(), source.stat().st_mtime)
    request = make_request(source, content=content)

    VaultEngine(sandbox_root, app_paths).capture(request)

    after = (source.read_bytes(), source.stat().st_mtime)
    assert after == before


def test_source_changed_before_capture_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    """Metadata (size/timestamps) matches, but expected_sha256 was computed
    from different content -- SOURCE_HASH_MISMATCH, not SOURCE_IDENTITY_
    CHANGED (which covers metadata mismatches instead; see
    test_source_replaced_by_symlink... and the missing/outside-sandbox
    tests for that family)."""
    source = make_source_file("report.txt", content=b"actual content")
    request = make_request(source, content=b"a different content entirely")

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.SOURCE_HASH_MISMATCH
    assert result.started_at is None
    assert result.completed_at is None
    assert source.read_bytes() == b"actual content"


def test_missing_source_is_rejected(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    source = make_source_file("gone.txt", content=b"x")
    request = make_request(source, content=b"x")
    source.unlink()

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.SOURCE_NOT_FOUND


def test_source_outside_sandbox_is_rejected(
    tmp_path: Path,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "a.txt"
    outside_file.write_bytes(b"outside content")
    request = make_request(outside_file, content=b"outside content")

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.SOURCE_OUTSIDE_SANDBOX


def test_same_hash_captured_twice_is_idempotent(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    content = b"captured twice"
    source = make_source_file("report.txt", content=content)
    request = make_request(source, content=content)
    engine = VaultEngine(sandbox_root, app_paths)

    first = engine.capture(request)
    assert first.status is VaultCaptureStatus.CAPTURED
    final_path = object_abs_path(app_paths, first.verified_sha256)  # type: ignore[arg-type]
    mtime_after_first = final_path.stat().st_mtime

    second_source = make_source_file("copy.txt", content=content)
    second_request = make_request(second_source, content=content)
    second = engine.capture(second_request)

    assert second.status is VaultCaptureStatus.ALREADY_PRESENT
    assert second.verified_sha256 == first.verified_sha256
    assert second.vault_object_path == first.vault_object_path
    assert final_path.stat().st_mtime == mtime_after_first  # never rewritten
    assert list(tmp_dir(app_paths).iterdir()) == []


def test_existing_corrupted_vault_object_is_rejected_and_left_untouched(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    content = b"real content"
    source = make_source_file("report.txt", content=content)
    request = make_request(source, content=content)

    expected_sha = hashlib.sha256(content).hexdigest()
    corrupted_path = object_abs_path(app_paths, expected_sha)
    corrupted_path.parent.mkdir(parents=True, exist_ok=True)
    corrupted_path.write_bytes(b"corrupted -- does not match its own filename hash")

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.EXISTING_VAULT_OBJECT_CORRUPTED
    assert (
        corrupted_path.read_bytes()
        == b"corrupted -- does not match its own filename hash"
    )
    assert list(tmp_dir(app_paths).iterdir()) == []


def test_source_changed_between_reverification_and_copy_is_rejected_and_cleans_up_temp(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    """Simulates the narrow TOCTOU window between FileHasher's reverification
    and the copy loop's own open() -- the window step 3+4's independent
    digest is specifically designed to detect (design plan: "source changed
    during capture, where detectable")."""
    source = make_source_file("report.txt", content=b"original content")
    request = make_request(source, content=b"original content")

    real_hash_file = FileHasher.hash_file

    def _hash_file_then_mutate(self: FileHasher, discovered: object) -> object:
        outcome = real_hash_file(self, discovered)  # type: ignore[arg-type]
        source.write_bytes(b"mutated after reverification, before copy")
        return outcome

    monkeypatch.setattr(FileHasher, "hash_file", _hash_file_then_mutate)

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.SOURCE_CHANGED_DURING_CAPTURE
    assert result.started_at is not None
    assert result.completed_at is not None
    assert list(tmp_dir(app_paths).iterdir()) == []


def test_source_replaced_by_symlink_between_reverification_and_copy_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    """Windows-specific: the copy loop's own is_symlink()/isjunction() check
    immediately before open(), distinct from FileHasher's own reparse check
    (which already passed once, before the swap)."""
    source = sandbox_root.path / "a.txt"
    source.write_bytes(b"original")
    other_target = sandbox_root.path / "other.txt"
    other_target.write_bytes(b"other content")
    request = make_request(source, content=b"original")

    real_hash_file = FileHasher.hash_file

    def _hash_file_then_swap(self: FileHasher, discovered: object) -> object:
        outcome = real_hash_file(self, discovered)  # type: ignore[arg-type]
        source.unlink()
        try:
            source.symlink_to(other_target)
        except OSError:
            pytest.skip(
                "symlink creation requires elevated privilege or Developer Mode on this host"
            )
        return outcome

    monkeypatch.setattr(FileHasher, "hash_file", _hash_file_then_swap)

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert result.status is VaultCaptureStatus.REJECTED
    assert result.rejection_code is VaultRejectionCode.SOURCE_CHANGED_DURING_CAPTURE
    assert list(tmp_dir(app_paths).iterdir()) == []


def test_result_round_trips_through_pydantic_validation(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., VaultCaptureRequest],
) -> None:
    """capture() never raises for well-formed input -- every branch must
    produce a VaultCaptureResult that satisfies its own status invariants
    (construction would raise ValidationError otherwise)."""
    source = make_source_file("report.txt", content=b"x")
    request = make_request(source, content=b"x")

    result = VaultEngine(sandbox_root, app_paths).capture(request)

    assert isinstance(result, VaultCaptureResult)
