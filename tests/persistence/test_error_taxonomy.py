"""Tests for the persistence error taxonomy's translation boundary."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.persistence import AppPaths, create_engine_and_session_factory, mapping
from file_agent.persistence.errors import DatabaseUnavailableError, MappingError
from file_agent.persistence.orm import ScanRow


def test_unwritable_app_data_root_raises_database_unavailable(tmp_path: Path) -> None:
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("x")
    config = AppPaths.from_root(
        blocking_file / "appdata"
    )  # a path segment is a FILE, not a dir
    with pytest.raises(DatabaseUnavailableError):
        create_engine_and_session_factory(config)


def test_bad_enum_value_in_row_raises_mapping_error() -> None:
    row = ScanRow(
        id=uuid4(),
        root_path="C:/sandbox",
        started_at=datetime.now(UTC),
        completed_at=None,
        files_discovered=0,
        status="not_a_real_status",
    )
    with pytest.raises(MappingError):
        mapping.row_to_scan(row)
