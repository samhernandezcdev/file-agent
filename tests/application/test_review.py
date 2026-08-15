"""Review flow: approve_review()/skip_review() persist a genuine
HumanReviewDecision built internally by HumanReviewEngine -- never accepting
a caller-constructed decision."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.application import ApplicationOutcomeStatus, FileAgentApplicationService
from file_agent.domain import PolicyDecision, PolicyOutcome
from file_agent.persistence import FileAgentStore
from file_agent.policy_engine import policy_decision_event


def test_approve_on_genuine_review(
    service: FileAgentApplicationService, make_source_file: Callable[..., Path]
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_scan().items[0]
    assert item.policy_outcome is PolicyOutcome.REVIEW

    result = service.approve_review(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED
    assert result.reason_code is None


def test_skip_on_genuine_review(
    service: FileAgentApplicationService, make_source_file: Callable[..., Path]
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_scan().items[0]

    result = service.skip_review(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.SUCCEEDED


def test_auto_cannot_be_reviewed(
    service: FileAgentApplicationService, make_source_file: Callable[..., Path]
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_scan().items[0]
    assert item.policy_outcome is PolicyOutcome.AUTO

    result = service.approve_review(item.policy_decision_id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "not_eligible_for_review"


def test_block_cannot_be_reviewed(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("report.pdf", content=b"pdf content")
    item = service.analyze_scan().items[0]
    blocked = PolicyDecision(
        proposal_id=item.proposal_id,
        file_id=item.file_id,
        decision=PolicyOutcome.BLOCK,
        reasons=("blocked for test",),
        evaluated_at=datetime.now(UTC),
        policy_engine_id="policy-v1",
        source_category=item.category,
        destination_category=item.proposed_destination_category,
        proposal_confidence=item.confidence,
        proposal_engine_id="rules-v1",
    )
    store.record_event(policy_decision_event(blocked))

    result = service.approve_review(blocked.id)

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "not_eligible_for_review"


def test_duplicate_same_decision_rejected(
    service: FileAgentApplicationService, make_source_file: Callable[..., Path]
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_scan().items[0]

    first = service.approve_review(item.policy_decision_id)
    assert first.status is ApplicationOutcomeStatus.SUCCEEDED
    second = service.approve_review(item.policy_decision_id)

    assert second.status is ApplicationOutcomeStatus.REJECTED
    assert second.reason_code == "already_reviewed"


def test_conflicting_decision_rejected(
    service: FileAgentApplicationService, make_source_file: Callable[..., Path]
) -> None:
    make_source_file("app.exe", content=b"exe content")
    item = service.analyze_scan().items[0]

    first = service.approve_review(item.policy_decision_id)
    assert first.status is ApplicationOutcomeStatus.SUCCEEDED
    second = service.skip_review(item.policy_decision_id)

    assert second.status is ApplicationOutcomeStatus.REJECTED
    assert second.reason_code == "already_reviewed"


def test_missing_policy_decision_rejected(service: FileAgentApplicationService) -> None:
    result = service.approve_review(uuid4())

    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "policy_decision_not_found"
