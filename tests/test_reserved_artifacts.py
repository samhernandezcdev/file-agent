"""reserved_artifacts.is_file_agent_internal_artifact -- matches the
reserved restore-temp prefix, rejects ordinary filenames. Consumed by
recovery_engine now; will be consumed by the scanner once the mandatory
FA-011.1 follow-up lands (not implemented here -- see recovery_engine's
design docs)."""

from file_agent.reserved_artifacts import (
    RESTORE_TEMP_PREFIX,
    is_file_agent_internal_artifact,
)


def test_reserved_prefix_matches() -> None:
    assert is_file_agent_internal_artifact(f"{RESTORE_TEMP_PREFIX}abc123.partial")


def test_ordinary_filenames_do_not_match() -> None:
    assert not is_file_agent_internal_artifact("report.txt")
    assert not is_file_agent_internal_artifact(".hidden_file")
    assert not is_file_agent_internal_artifact(
        "file_agent_restore.txt"
    )  # missing leading dot


def test_prefix_match_is_prefix_not_substring() -> None:
    assert not is_file_agent_internal_artifact(
        f"not_at_start{RESTORE_TEMP_PREFIX}abc.partial"
    )
