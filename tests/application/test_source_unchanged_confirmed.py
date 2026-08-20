"""FA-017.3 (Round 2 Major 2): source_unchanged_confirmed semantics.

True means FileAgent has positive evidence the expected original source
file is still present, unchanged, at its original location. False means
that positive claim cannot be made -- never "FileAgent moved/modified it"
or "a partial move occurred". Every pre-commit rejection is guaranteed
True by construction (TransactionEngine.prepare() never mutates); the
FAILED (commit() OSError) case is the one that requires a genuine,
read-only, post-failure identity reverification, reusing
transaction_engine.preconditions.verify_source_identity -- the exact same
mechanism prepare() itself already uses.
"""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from file_agent.application import ApplicationOutcomeStatus, FileAgentApplicationService
from file_agent.domain import PolicyOutcome
from file_agent.scanner import SandboxRoot


def test_pre_commit_application_rejection_confirms_source_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    """A REVIEW item with no approval is rejected before TransactionEngine
    is ever constructed."""
    make_source_file("app.exe", content=b"exe content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]
    assert item.policy_outcome is PolicyOutcome.REVIEW

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.source_unchanged_confirmed is True


def test_transaction_engine_prepare_rejection_confirms_source_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """Analyze with only the source file present, THEN occupy the
    destination -- so the scanner never sees two files (which would
    otherwise itself get discovered and misclassify as
    SOURCE_EQUALS_DESTINATION) and prepare() itself rejects with
    DESTINATION_ALREADY_EXISTS, a genuine TransactionEngine.prepare()
    rejection, not a pre-engine application-level one."""
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    (sandbox_root.path / "Documents").mkdir(exist_ok=True)
    (sandbox_root.path / "Documents" / "report.pdf").write_bytes(b"already there")

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "destination_already_exists"
    assert result.source_unchanged_confirmed is True
    # FA-017.3 Major-2-adjacent fix: destination is no longer discarded for
    # a REJECTED TransactionEngine result.
    assert result.destination_path == sandbox_root.path / "Documents" / "report.pdf"


def test_commit_os_error_with_source_still_matching_confirms_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move raises OSError but the source file is left exactly as it
    was -- a fresh identity reverification should positively confirm it."""
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated OS-level move failure")

    monkeypatch.setattr("file_agent.transaction_engine.engine.move_no_replace", _raise)

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.FAILED
    assert result.source_unchanged_confirmed is True


def test_commit_os_error_with_source_missing_does_not_confirm_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move raises OSError, and the source has also vanished (some
    external interference) -- False, and never a "FileAgent moved it"
    implication anywhere in the returned data."""
    source = make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    def _raise_after_deleting_source(*_args: object, **_kwargs: object) -> None:
        source.unlink()
        raise OSError("simulated OS-level move failure")

    monkeypatch.setattr(
        "file_agent.transaction_engine.engine.move_no_replace",
        _raise_after_deleting_source,
    )

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.FAILED
    assert result.source_unchanged_confirmed is False


def test_commit_os_error_with_different_file_at_source_does_not_confirm_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely different file now occupies the source path -- fresh
    identity reverification must catch this (hash/metadata mismatch), not
    just check existence."""
    source = make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    def _raise_after_swapping_source(*_args: object, **_kwargs: object) -> None:
        source.unlink()
        source.write_bytes(b"a completely different file, same name")
        raise OSError("simulated OS-level move failure")

    monkeypatch.setattr(
        "file_agent.transaction_engine.engine.move_no_replace",
        _raise_after_swapping_source,
    )

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.FAILED
    assert result.source_unchanged_confirmed is False


def test_commit_os_error_when_verification_itself_raises_does_not_confirm_unchanged(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-failure verification call itself raises -- fails closed to
    False, and (critically) the exception never replaces or masks the
    original, truthful FAILED apply result."""
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated OS-level move failure")

    def _raise_verification(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated unexpected verification failure")

    monkeypatch.setattr("file_agent.transaction_engine.engine.move_no_replace", _raise)
    monkeypatch.setattr(
        "file_agent.application.service.verify_source_identity", _raise_verification
    )

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.FAILED
    assert result.source_unchanged_confirmed is False
    assert result.reason == "simulated OS-level move failure"


def test_succeeded_result_has_a_source_unchanged_confirmed_value_but_it_is_not_meaningful(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    make_source_file: Callable[..., Path],
) -> None:
    """SUCCEEDED always populates the field (it's a plain bool, never
    Optional) but its value is product-irrelevant and must never be
    rendered -- covered separately by the presentation-layer tests, this
    just proves the field exists and apply_item doesn't crash."""
    make_source_file("report.pdf", content=b"pdf content")
    analysis = service.analyze_managed_root(managed_root_id)
    item = analysis.items[0]

    result = service.apply_item(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert isinstance(result.source_unchanged_confirmed, bool)
