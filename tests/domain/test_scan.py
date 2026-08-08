"""Tests for ScanRun."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from file_agent.domain import ScanRun, ScanStatus


def _make(tmp_path: Path, **overrides: object) -> ScanRun:
    defaults: dict[str, object] = {
        "root_path": tmp_path,
        "started_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return ScanRun(**defaults)


def test_default_construction(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    assert scan.status is ScanStatus.PENDING
    assert scan.completed_at is None
    assert scan.files_discovered == 0


def test_non_absolute_root_path_rejected() -> None:
    with pytest.raises(ValidationError):
        ScanRun(root_path=Path("relative/dir"), started_at=datetime.now(UTC))


def test_frozen_mutation_raises(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValidationError):
        scan.files_discovered = 5  # type: ignore[misc]


def test_evolve_valid_transition(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    completed = scan.evolve(
        status=ScanStatus.COMPLETED,
        completed_at=scan.started_at + timedelta(seconds=1),
        files_discovered=42,
    )
    assert completed is not scan
    assert scan.status is ScanStatus.PENDING  # original snapshot untouched
    assert completed.status is ScanStatus.COMPLETED
    assert completed.files_discovered == 42
    assert completed.id == scan.id


def test_evolve_rejects_completed_without_completed_at(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValidationError):
        scan.evolve(status=ScanStatus.COMPLETED)


def test_evolve_rejects_failed_without_completed_at(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValidationError):
        scan.evolve(status=ScanStatus.FAILED)


def test_evolve_rejects_completed_at_before_started_at(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValidationError):
        scan.evolve(
            status=ScanStatus.COMPLETED,
            completed_at=scan.started_at - timedelta(seconds=1),
        )


def test_files_discovered_negative_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, files_discovered=-1)


def test_naive_started_at_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, started_at=datetime.now())  # noqa: DTZ005 -- intentionally naive


def test_aware_non_utc_started_at_normalized(tmp_path: Path) -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    scan = _make(tmp_path, started_at=local)
    assert scan.started_at.tzinfo == UTC
    assert scan.started_at.hour == 10


def test_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, bogus_field="nope")


# --- M2: evolve() may only change lifecycle/progress fields --------------------


def test_evolve_rejects_id_change(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValueError, match="id"):
        scan.evolve(id=uuid4())


def test_evolve_rejects_root_path_change(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    scan = _make(tmp_path)
    other_root = tmp_path_factory.mktemp("other")
    with pytest.raises(ValueError, match="root_path"):
        scan.evolve(root_path=other_root)


def test_evolve_rejects_started_at_change(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValueError, match="started_at"):
        scan.evolve(started_at=scan.started_at + timedelta(seconds=1))


def test_evolve_rejects_unknown_field(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    with pytest.raises(ValueError, match="statuss"):
        scan.evolve(statuss=ScanStatus.RUNNING)


def test_evolve_allows_lifecycle_fields_only(tmp_path: Path) -> None:
    scan = _make(tmp_path)
    running = scan.evolve(status=ScanStatus.RUNNING, files_discovered=7)
    assert running.status is ScanStatus.RUNNING
    assert running.files_discovered == 7
    assert running.id == scan.id
    assert running.root_path == scan.root_path
    assert running.started_at == scan.started_at
