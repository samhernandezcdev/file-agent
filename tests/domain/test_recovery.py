"""Tests for CompletedMoveEvidence/VaultCaptureEvidence factories and
ReverseMoveRequest/RestoreFromVaultRequest/RecoveryResult invariants."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    CompletedMoveEvidence,
    DestinationCategory,
    RecoveryOperation,
    RecoveryRejectionCode,
    RecoveryResult,
    RecoveryStatus,
    RestoreFromVaultRequest,
    ReverseMoveRequest,
    TransactionOperation,
    TransactionResult,
    TransactionStatus,
    VaultCaptureEvidence,
    VaultCaptureResult,
    VaultCaptureStatus,
)

_SHA = "a" * 64


def _make_transaction_result(**overrides: object) -> TransactionResult:
    defaults: dict[str, object] = {
        "request_id": uuid4(),
        "file_id": uuid4(),
        "proposal_id": uuid4(),
        "policy_decision_id": uuid4(),
        "operation": TransactionOperation.MOVE,
        "source_path": Path(r"C:\sandbox\report.txt"),
        "destination_path": Path(r"C:\sandbox\Documents\report.txt"),
        "destination_category": DestinationCategory.DOCUMENTS,
        "expected_sha256": _SHA,
        "expected_size": 10,
        "status": TransactionStatus.SUCCEEDED,
        "verified_sha256": _SHA,
        "evaluated_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "transaction_engine_id": "v1",
    }
    defaults.update(overrides)
    return TransactionResult(**defaults)


def test_completed_move_evidence_from_succeeded_transaction_result() -> None:
    result = _make_transaction_result()

    evidence = CompletedMoveEvidence.from_transaction_result(result)

    assert evidence.original_transaction_id == result.request_id
    assert evidence.file_id == result.file_id
    assert evidence.source_path == result.source_path
    assert evidence.destination_path == result.destination_path
    assert evidence.verified_sha256 == result.verified_sha256


@pytest.mark.parametrize(
    "status", [TransactionStatus.REJECTED, TransactionStatus.FAILED]
)
def test_completed_move_evidence_refuses_non_succeeded_result(
    status: TransactionStatus,
) -> None:
    overrides: dict[str, object] = {"status": status, "verified_sha256": None}
    if status is TransactionStatus.REJECTED:
        from file_agent.domain import RejectionCode

        overrides["rejection_code"] = RejectionCode.SOURCE_NOT_FOUND
        overrides["started_at"] = None
        overrides["completed_at"] = None
    else:
        overrides["failure_reason"] = "disk full"
    result = _make_transaction_result(**overrides)

    with pytest.raises(ValueError, match="non-SUCCEEDED"):
        CompletedMoveEvidence.from_transaction_result(result)


def _make_vault_capture_result(**overrides: object) -> VaultCaptureResult:
    defaults: dict[str, object] = {
        "request_id": uuid4(),
        "file_id": uuid4(),
        "source_path": Path(r"C:\sandbox\report.txt"),
        "expected_sha256": _SHA,
        "expected_size": 10,
        "status": VaultCaptureStatus.CAPTURED,
        "verified_sha256": _SHA,
        "verified_size": 10,
        "vault_object_path": f"objects/{_SHA[:2]}/{_SHA}",
        "evaluated_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "vault_engine_id": "v1",
    }
    defaults.update(overrides)
    return VaultCaptureResult(**defaults)


def test_vault_capture_evidence_from_captured_result() -> None:
    result = _make_vault_capture_result()

    evidence = VaultCaptureEvidence.from_capture_result(result)

    assert evidence.file_id == result.file_id
    assert evidence.source_path == result.source_path
    assert evidence.verified_sha256 == result.verified_sha256


def test_vault_capture_evidence_from_already_present_result() -> None:
    result = _make_vault_capture_result(status=VaultCaptureStatus.ALREADY_PRESENT)
    evidence = VaultCaptureEvidence.from_capture_result(result)
    assert evidence.verified_sha256 == result.verified_sha256


def test_vault_capture_evidence_refuses_rejected_result() -> None:
    from file_agent.domain import VaultRejectionCode

    result = _make_vault_capture_result(
        status=VaultCaptureStatus.REJECTED,
        rejection_code=VaultRejectionCode.SOURCE_NOT_FOUND,
        verified_sha256=None,
        verified_size=None,
        vault_object_path=None,
        started_at=None,
        completed_at=None,
    )
    with pytest.raises(ValueError, match="non-successful"):
        VaultCaptureEvidence.from_capture_result(result)


def _make_move_evidence(**overrides: object) -> CompletedMoveEvidence:
    defaults: dict[str, object] = {
        "original_transaction_id": uuid4(),
        "file_id": uuid4(),
        "source_path": Path(r"C:\sandbox\report.txt"),
        "destination_path": Path(r"C:\sandbox\Documents\report.txt"),
        "verified_sha256": _SHA,
    }
    defaults.update(overrides)
    return CompletedMoveEvidence(**defaults)


def _make_vault_evidence(**overrides: object) -> VaultCaptureEvidence:
    defaults: dict[str, object] = {
        "file_id": uuid4(),
        "source_path": Path(r"C:\sandbox\report.txt"),
        "verified_sha256": _SHA,
    }
    defaults.update(overrides)
    return VaultCaptureEvidence(**defaults)


def test_reverse_move_request_derives_from_evidence() -> None:
    evidence = _make_move_evidence()
    now = datetime.now(UTC)
    request = ReverseMoveRequest(
        evidence=evidence,
        expected_size=10,
        expected_created_at=now,
        expected_modified_at=now,
    )
    assert request.operation is RecoveryOperation.REVERSE_MOVE
    assert request.evidence.verified_sha256 == _SHA


def test_reverse_move_request_frozen_and_extra_forbidden() -> None:
    evidence = _make_move_evidence()
    now = datetime.now(UTC)
    request = ReverseMoveRequest(
        evidence=evidence,
        expected_size=10,
        expected_created_at=now,
        expected_modified_at=now,
    )
    with pytest.raises(ValidationError):
        request.expected_size = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ReverseMoveRequest(
            evidence=evidence,
            expected_size=10,
            expected_created_at=now,
            expected_modified_at=now,
            bogus="nope",
        )


def test_restore_from_vault_request_derives_from_evidence() -> None:
    evidence = _make_vault_evidence()
    request = RestoreFromVaultRequest(evidence=evidence)
    assert request.operation is RecoveryOperation.RESTORE_FROM_VAULT
    assert request.evidence.verified_sha256 == _SHA


def _make_result(**overrides: object) -> RecoveryResult:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "request_id": uuid4(),
        "operation": RecoveryOperation.REVERSE_MOVE,
        "file_id": uuid4(),
        "original_transaction_id": uuid4(),
        "source_path": Path(r"C:\sandbox\Documents\report.txt"),
        "destination_path": Path(r"C:\sandbox\report.txt"),
        "expected_sha256": _SHA,
        "vault_object_path": None,
        "status": RecoveryStatus.SUCCEEDED,
        "verified_sha256": _SHA,
        "evaluated_at": now,
        "started_at": now,
        "completed_at": now,
        "recovery_engine_id": "v1",
    }
    defaults.update(overrides)
    return RecoveryResult(**defaults)


def test_succeeded_reverse_move_result_valid() -> None:
    result = _make_result()
    assert result.status is RecoveryStatus.SUCCEEDED


def test_succeeded_reverse_move_forbids_vault_object_path() -> None:
    with pytest.raises(ValidationError):
        _make_result(vault_object_path="objects/aa/" + _SHA)


def test_succeeded_restore_requires_vault_object_path() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            operation=RecoveryOperation.RESTORE_FROM_VAULT,
            original_transaction_id=None,
            source_path=None,
            vault_object_path=None,
        )


def test_succeeded_restore_with_vault_object_path_valid() -> None:
    result = _make_result(
        operation=RecoveryOperation.RESTORE_FROM_VAULT,
        original_transaction_id=None,
        source_path=None,
        vault_object_path=f"objects/{_SHA[:2]}/{_SHA}",
    )
    assert result.vault_object_path is not None


def test_restore_source_path_must_be_none() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            operation=RecoveryOperation.RESTORE_FROM_VAULT,
            original_transaction_id=None,
            vault_object_path=f"objects/{_SHA[:2]}/{_SHA}",
        )


def test_reverse_move_source_path_must_not_be_none() -> None:
    with pytest.raises(ValidationError):
        _make_result(source_path=None)


def test_succeeded_verified_sha_must_equal_expected() -> None:
    with pytest.raises(ValidationError):
        _make_result(verified_sha256="b" * 64)


def test_rejected_permits_optional_timestamps() -> None:
    without = _make_result(
        status=RecoveryStatus.REJECTED,
        rejection_code=RecoveryRejectionCode.CURRENT_FILE_MISSING,
        verified_sha256=None,
        vault_object_path=None,
        started_at=None,
        completed_at=None,
    )
    assert without.started_at is None

    now = datetime.now(UTC)
    with_timestamps = _make_result(
        status=RecoveryStatus.REJECTED,
        rejection_code=RecoveryRejectionCode.RESTORED_BYTES_HASH_MISMATCH,
        verified_sha256=None,
        vault_object_path=None,
        started_at=now,
        completed_at=now,
    )
    assert with_timestamps.started_at is not None


def test_rejected_requires_rejection_code() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=RecoveryStatus.REJECTED,
            rejection_code=None,
            verified_sha256=None,
            vault_object_path=None,
            started_at=None,
            completed_at=None,
        )


def test_rejected_forbids_vault_object_path() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=RecoveryStatus.REJECTED,
            rejection_code=RecoveryRejectionCode.CURRENT_FILE_MISSING,
            verified_sha256=None,
            vault_object_path=f"objects/{_SHA[:2]}/{_SHA}",
            started_at=None,
            completed_at=None,
        )


def test_failed_requires_failure_reason_and_timestamps() -> None:
    with pytest.raises(ValidationError):
        _make_result(
            status=RecoveryStatus.FAILED,
            rejection_code=None,
            failure_reason=None,
            verified_sha256=None,
            vault_object_path=None,
        )


def test_started_after_completed_rejected() -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    with pytest.raises(ValidationError):
        _make_result(started_at=later, completed_at=earlier)


def test_result_frozen_and_extra_forbidden() -> None:
    result = _make_result()
    with pytest.raises(ValidationError):
        result.status = RecoveryStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _make_result(bogus="nope")


def test_started_at_normalizes_aware_non_utc() -> None:
    from datetime import timezone

    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    result = _make_result(started_at=local, completed_at=local)
    assert result.started_at is not None
    assert result.started_at.tzinfo == UTC
    assert result.started_at.hour == 10
