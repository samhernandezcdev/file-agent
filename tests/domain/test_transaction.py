"""Tests for TransactionRequest/TransactionResult domain invariants."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import (
    DestinationCategory,
    RejectionCode,
    TransactionOperation,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
)


def _make_request(tmp_path: Path, **overrides: object) -> TransactionRequest:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "file_id": uuid4(),
        "proposal_id": uuid4(),
        "policy_decision_id": uuid4(),
        "source_path": tmp_path / "sandbox" / "report.txt",
        "destination_path": tmp_path / "sandbox" / "Documents" / "report.txt",
        "destination_category": DestinationCategory.DOCUMENTS,
        "expected_size": 10,
        "expected_created_at": now,
        "expected_modified_at": now,
        "expected_sha256": "a" * 64,
    }
    defaults.update(overrides)
    return TransactionRequest(**defaults)


def test_valid_request_construction(tmp_path: Path) -> None:
    request = _make_request(tmp_path)
    assert request.operation is TransactionOperation.MOVE


def test_request_non_absolute_source_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_request(tmp_path, source_path=Path("relative/report.txt"))


def test_request_invalid_sha256_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_request(tmp_path, expected_sha256="not-a-hash")


def test_request_frozen_mutation_raises(tmp_path: Path) -> None:
    request = _make_request(tmp_path)
    with pytest.raises(ValidationError):
        request.source_path = Path("/other")  # type: ignore[misc]


def test_request_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_request(tmp_path, bogus_field="nope")


def _make_result(tmp_path: Path, **overrides: object) -> TransactionResult:
    defaults: dict[str, object] = {
        "request_id": uuid4(),
        "file_id": uuid4(),
        "proposal_id": uuid4(),
        "policy_decision_id": uuid4(),
        "operation": TransactionOperation.MOVE,
        "source_path": tmp_path / "sandbox" / "report.txt",
        "destination_path": tmp_path / "sandbox" / "Documents" / "report.txt",
        "destination_category": DestinationCategory.DOCUMENTS,
        "expected_sha256": "a" * 64,
        "expected_size": 10,
        "status": TransactionStatus.REJECTED,
        "rejection_code": RejectionCode.DESTINATION_ALREADY_EXISTS,
        "evaluated_at": datetime.now(UTC),
        "transaction_engine_id": "v1",
    }
    defaults.update(overrides)
    return TransactionResult(**defaults)


def test_valid_rejected_result_construction(tmp_path: Path) -> None:
    result = _make_result(tmp_path)
    assert result.status is TransactionStatus.REJECTED
    assert result.rejection_code is RejectionCode.DESTINATION_ALREADY_EXISTS
    assert result.started_at is None
    assert result.completed_at is None


def test_rejected_without_rejection_code_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_result(tmp_path, rejection_code=None)


def test_rejected_with_failure_reason_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_result(tmp_path, failure_reason="boom")


def test_rejected_with_started_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_result(tmp_path, started_at=datetime.now(UTC))


def test_rejected_with_completed_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_result(tmp_path, completed_at=datetime.now(UTC))


def _make_failed_result(tmp_path: Path, **overrides: object) -> TransactionResult:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "status": TransactionStatus.FAILED,
        "rejection_code": None,
        "failure_reason": "disk full",
        "started_at": now,
        "completed_at": now,
        "verified_sha256": "b" * 64,
    }
    defaults.update(overrides)
    return _make_result(tmp_path, **defaults)


def test_valid_failed_result_construction(tmp_path: Path) -> None:
    result = _make_failed_result(tmp_path)
    assert result.status is TransactionStatus.FAILED
    assert result.failure_reason == "disk full"


def test_failed_without_failure_reason_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_failed_result(tmp_path, failure_reason=None)


def test_failed_with_rejection_code_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_failed_result(tmp_path, rejection_code=RejectionCode.SOURCE_NOT_FOUND)


def test_failed_without_started_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_failed_result(tmp_path, started_at=None)


def test_failed_without_completed_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_failed_result(tmp_path, completed_at=None)


def _make_succeeded_result(tmp_path: Path, **overrides: object) -> TransactionResult:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "status": TransactionStatus.SUCCEEDED,
        "rejection_code": None,
        "started_at": now,
        "completed_at": now,
        "verified_sha256": "c" * 64,
    }
    defaults.update(overrides)
    return _make_result(tmp_path, **defaults)


def test_valid_succeeded_result_construction(tmp_path: Path) -> None:
    result = _make_succeeded_result(tmp_path)
    assert result.status is TransactionStatus.SUCCEEDED
    assert result.verified_sha256 == "c" * 64


def test_succeeded_without_verified_sha256_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, verified_sha256=None)


def test_succeeded_with_rejection_code_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, rejection_code=RejectionCode.SOURCE_NOT_FOUND)


def test_succeeded_with_failure_reason_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, failure_reason="oops")


def test_succeeded_without_started_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, started_at=None)


def test_succeeded_without_completed_at_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, completed_at=None)


def test_started_after_completed_is_rejected(tmp_path: Path) -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    with pytest.raises(ValidationError):
        _make_succeeded_result(tmp_path, started_at=later, completed_at=earlier)


def test_result_frozen_mutation_raises(tmp_path: Path) -> None:
    result = _make_result(tmp_path)
    with pytest.raises(ValidationError):
        result.status = TransactionStatus.SUCCEEDED  # type: ignore[misc]


def test_result_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make_result(tmp_path, bogus_field="nope")
