"""Tests for VaultCaptureRequest/VaultCaptureResult/VaultObject invariants."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    VaultCaptureRequest,
    VaultCaptureResult,
    VaultCaptureStatus,
    VaultObject,
    VaultRejectionCode,
)

_VALID_SHA = "a" * 64


def _make_request(**overrides: object) -> VaultCaptureRequest:
    defaults: dict[str, object] = {
        "file_id": uuid4(),
        "source_path": r"C:\sandbox\report.txt",
        "expected_size": 10,
        "expected_created_at": datetime.now(UTC),
        "expected_modified_at": datetime.now(UTC),
        "expected_sha256": _VALID_SHA,
    }
    defaults.update(overrides)
    from pathlib import Path

    if isinstance(defaults["source_path"], str):
        defaults["source_path"] = Path(defaults["source_path"])
    return VaultCaptureRequest(**defaults)


def _make_result(**overrides: object) -> VaultCaptureResult:
    from pathlib import Path

    defaults: dict[str, object] = {
        "request_id": uuid4(),
        "file_id": uuid4(),
        "source_path": Path(r"C:\sandbox\report.txt"),
        "expected_sha256": _VALID_SHA,
        "expected_size": 10,
        "status": VaultCaptureStatus.CAPTURED,
        "verified_sha256": _VALID_SHA,
        "verified_size": 10,
        "vault_object_path": f"objects/{_VALID_SHA[:2]}/{_VALID_SHA}",
        "evaluated_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "vault_engine_id": "v1",
    }
    defaults.update(overrides)
    return VaultCaptureResult(**defaults)


def test_request_requires_absolute_source_path() -> None:
    from pathlib import Path

    with pytest.raises(ValidationError):
        _make_request(source_path=Path("relative/report.txt"))


def test_request_invalid_sha256_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_request(expected_sha256="not-a-hash")


def test_request_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_request(expected_created_at=datetime.now())  # noqa: DTZ005 -- intentionally naive


def test_request_aware_non_utc_datetime_normalized() -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    request = _make_request(expected_modified_at=local)
    assert request.expected_modified_at.tzinfo == UTC
    assert request.expected_modified_at.hour == 10


def test_request_frozen_and_extra_forbidden() -> None:
    request = _make_request()
    with pytest.raises(ValidationError):
        request.expected_size = 999  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _make_request(bogus="nope")


def test_result_captured_requires_verification_fields() -> None:
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.CAPTURED, verified_sha256=None)
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.CAPTURED, vault_object_path=None)
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.CAPTURED, started_at=None)


def test_result_captured_verified_sha_must_equal_expected() -> None:
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.CAPTURED, verified_sha256="b" * 64)


def test_result_captured_forbids_rejection_code_and_failure_reason() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.CAPTURED,
            rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
        )
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.CAPTURED, failure_reason="oops")


def test_result_already_present_same_invariants_as_captured() -> None:
    result = _make_result(status=VaultCaptureStatus.ALREADY_PRESENT)
    assert result.status is VaultCaptureStatus.ALREADY_PRESENT
    with pytest.raises(ValidationError):
        _make_result(status=VaultCaptureStatus.ALREADY_PRESENT, verified_sha256=None)


def test_result_rejected_requires_rejection_code() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.REJECTED,
            rejection_code=None,
            verified_sha256=None,
            verified_size=None,
            vault_object_path=None,
            started_at=None,
            completed_at=None,
        )


def test_result_rejected_forbids_vault_object_path() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.REJECTED,
            rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
            verified_sha256=None,
            verified_size=None,
            started_at=None,
            completed_at=None,
        )


def test_result_rejected_forbids_failure_reason() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.REJECTED,
            rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
            failure_reason="oops",
            verified_sha256=None,
            verified_size=None,
            vault_object_path=None,
            started_at=None,
            completed_at=None,
        )


def test_result_rejected_permits_optional_timestamps() -> None:
    """Deliberate divergence from TransactionResult (design plan): a
    rejected capture MAY have already performed Vault I/O (e.g.
    EXISTING_VAULT_OBJECT_CORRUPTED is only discoverable after a read)."""
    without_timestamps = _make_result(
        status=VaultCaptureStatus.REJECTED,
        rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
        verified_sha256=None,
        verified_size=None,
        vault_object_path=None,
        started_at=None,
        completed_at=None,
    )
    assert without_timestamps.started_at is None

    with_timestamps = _make_result(
        status=VaultCaptureStatus.REJECTED,
        rejection_code=VaultRejectionCode.EXISTING_VAULT_OBJECT_CORRUPTED,
        verified_sha256=None,
        verified_size=None,
        vault_object_path=None,
    )
    assert with_timestamps.started_at is not None


def test_result_failed_requires_failure_reason_and_timestamps() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.FAILED,
            failure_reason=None,
            rejection_code=None,
            verified_sha256=None,
            verified_size=None,
            vault_object_path=None,
        )
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.FAILED,
            failure_reason="copy failed",
            rejection_code=None,
            verified_sha256=None,
            verified_size=None,
            vault_object_path=None,
            started_at=None,
            completed_at=None,
        )


def test_result_failed_forbids_rejection_code_and_vault_object_path() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.FAILED,
            failure_reason="copy failed",
            rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
            verified_sha256=None,
            verified_size=None,
            vault_object_path=None,
        )
    with pytest.raises(ValidationError):
        _make_result(
            status=VaultCaptureStatus.FAILED,
            failure_reason="copy failed",
            rejection_code=None,
            verified_sha256=None,
            verified_size=None,
        )


def test_result_started_after_completed_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        _make_result(started_at=now, completed_at=now - timedelta(seconds=1))


def test_result_invalid_verified_sha_shape_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_result(verified_sha256="not-a-hash")


def test_result_frozen_and_extra_forbidden() -> None:
    result = _make_result()
    with pytest.raises(ValidationError):
        result.status = VaultCaptureStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _make_result(bogus="nope")


def test_vault_object_carries_no_capture_provenance() -> None:
    """Round-2 correction: VaultObject is only physical identity -- no
    source_file_id/source_path/captured_at fields exist on it at all."""
    obj = VaultObject(
        sha256=_VALID_SHA,
        size_bytes=10,
        vault_relative_path=f"objects/{_VALID_SHA[:2]}/{_VALID_SHA}",
        vault_engine_id="v1",
    )
    assert not hasattr(obj, "source_file_id")
    assert not hasattr(obj, "source_path")
    assert not hasattr(obj, "captured_at")


def test_vault_object_invalid_sha_rejected() -> None:
    with pytest.raises(ValidationError):
        VaultObject(
            sha256="not-a-hash",
            size_bytes=10,
            vault_relative_path="objects/xx/not-a-hash",
            vault_engine_id="v1",
        )


def test_vault_object_frozen_and_extra_forbidden() -> None:
    obj = VaultObject(
        sha256=_VALID_SHA,
        size_bytes=10,
        vault_relative_path=f"objects/{_VALID_SHA[:2]}/{_VALID_SHA}",
        vault_engine_id="v1",
    )
    with pytest.raises(ValidationError):
        obj.size_bytes = 999  # type: ignore[misc]
    with pytest.raises(ValidationError):
        VaultObject(
            sha256=_VALID_SHA,
            size_bytes=10,
            vault_relative_path="x",
            vault_engine_id="v1",
            bogus="nope",
        )
