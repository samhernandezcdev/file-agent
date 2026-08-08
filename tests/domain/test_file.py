"""Tests for DiscoveredFile."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from file_agent.domain import DiscoveredFile


def _make(tmp_path: Path, **overrides: object) -> DiscoveredFile:
    defaults: dict[str, object] = {
        "path": tmp_path / "report.PDF",
        "size_bytes": 1234,
        "created_at": datetime.now(UTC),
        "modified_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return DiscoveredFile(**defaults)


def test_valid_construction_has_unique_ids(tmp_path: Path) -> None:
    a = _make(tmp_path)
    b = _make(tmp_path)
    assert isinstance(a.id, UUID)
    assert a.id != b.id


def test_size_bytes_negative_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, size_bytes=-1)


def test_size_bytes_zero_accepted(tmp_path: Path) -> None:
    assert _make(tmp_path, size_bytes=0).size_bytes == 0


def test_sha256_none_accepted(tmp_path: Path) -> None:
    assert _make(tmp_path, sha256=None).sha256 is None


def test_sha256_valid_accepted(tmp_path: Path, valid_sha256: str) -> None:
    assert _make(tmp_path, sha256=valid_sha256).sha256 == valid_sha256


@pytest.mark.parametrize(
    "bad_hash",
    [
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "A" * 64,
    ],
)
def test_sha256_invalid_rejected(tmp_path: Path, bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, sha256=bad_hash)


def test_relative_path_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, path=Path("relative/report.pdf"))


def test_absolute_path_accepted(tmp_path: Path) -> None:
    assert _make(tmp_path).path.is_absolute()


def test_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, bogus_field="nope")


def test_frozen_mutation_raises(tmp_path: Path) -> None:
    discovered = _make(tmp_path)
    with pytest.raises(ValidationError):
        discovered.path = Path("/other")  # type: ignore[misc]


@pytest.mark.parametrize("field", ["created_at", "modified_at", "discovered_at"])
def test_naive_datetime_rejected(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, **{field: datetime.now()})  # noqa: DTZ005 -- intentionally naive


def test_aware_non_utc_datetime_normalized(tmp_path: Path) -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two)
    discovered = _make(tmp_path, created_at=local)
    assert discovered.created_at == local
    assert discovered.created_at.tzinfo == UTC
    assert discovered.created_at.hour == 10


# --- M4: filename/extension derived from path -------------------------------


def test_filename_derived_from_path(tmp_path: Path) -> None:
    discovered = _make(tmp_path, path=tmp_path / "report.pdf")
    assert discovered.filename == "report.pdf"


def test_extension_derived_and_normalized(tmp_path: Path) -> None:
    discovered = _make(tmp_path, path=tmp_path / "report.PDF")
    assert discovered.extension == "pdf"


def test_extensionless_file(tmp_path: Path) -> None:
    discovered = _make(tmp_path, path=tmp_path / "LICENSE")
    assert discovered.filename == "LICENSE"
    assert discovered.extension == ""


def test_multi_suffix_filename_uses_final_suffix_only(tmp_path: Path) -> None:
    discovered = _make(tmp_path, path=tmp_path / "archive.tar.gz")
    assert discovered.filename == "archive.tar.gz"
    assert discovered.extension == "gz"


def test_windows_absolute_path_filename_and_extension() -> None:
    discovered = DiscoveredFile(
        path=Path(r"C:\Users\test\notes.TXT"),
        size_bytes=10,
        created_at=datetime.now(UTC),
        modified_at=datetime.now(UTC),
    )
    assert discovered.filename == "notes.TXT"
    assert discovered.extension == "txt"


def test_filename_and_extension_cannot_be_passed_independently(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _make(tmp_path, filename="spoofed.pdf")
    with pytest.raises(ValidationError):
        _make(tmp_path, extension="pdf")


# --- M3: with_sha256 ----------------------------------------------------------


def test_with_sha256_returns_new_instance_original_unchanged(
    tmp_path: Path, valid_sha256: str
) -> None:
    original = _make(tmp_path, sha256=None)
    hashed = original.with_sha256(valid_sha256)
    assert original.sha256 is None
    assert hashed.sha256 == valid_sha256
    assert hashed is not original


def test_with_sha256_preserves_id_and_other_fields(
    tmp_path: Path, valid_sha256: str
) -> None:
    original = _make(tmp_path)
    hashed = original.with_sha256(valid_sha256)
    assert hashed.id == original.id
    assert hashed.path == original.path
    assert hashed.size_bytes == original.size_bytes
    assert hashed.created_at == original.created_at
    assert hashed.modified_at == original.modified_at


def test_with_sha256_rejects_invalid_hash(tmp_path: Path) -> None:
    original = _make(tmp_path)
    with pytest.raises(ValidationError):
        original.with_sha256("not-a-valid-hash")
