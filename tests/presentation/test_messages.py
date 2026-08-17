"""Message-construction behavior (severity/suggested_action mapping,
source-changed -> REANALYZE override, batch/history summary phrasing).
Built with plain constructed DTOs -- presentation/ is a pure rendering
layer, it never needs a real store or sandbox."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from file_agent.application.dto import (
    BatchApplyItemResult,
    BatchApplyItemStatus,
    BatchApplyResult,
    BatchApplySummary,
    BatchStatus,
)
from file_agent.application.history import BatchHistoryEntry, UnavailableBatchHistoryRow
from file_agent.application.organization_plan import (
    OrganizationPlanItem,
    PlanReasonCode,
    PlanStatus,
)
from file_agent.domain import FileCategory, PolicyOutcome
from file_agent.presentation import es
from file_agent.presentation.messages import Severity, SuggestedAction


def _plan_item(
    *, status: PlanStatus, reason_code: PlanReasonCode | None
) -> OrganizationPlanItem:
    return OrganizationPlanItem(
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        source_path=Path("C:/sandbox/report.pdf"),
        filename="report.pdf",
        category=FileCategory.DOCUMENT,
        destination_category=None,
        destination_path=None,
        policy_outcome=PolicyOutcome.AUTO,
        human_review_outcome=None,
        status=status,
        reason_code=reason_code,
        reason="irrelevant prose, never rendered directly",
    )


def _batch_item(
    *, status: BatchApplyItemStatus, reason_code: str | None
) -> BatchApplyItemResult:
    return BatchApplyItemResult(
        policy_decision_id=uuid4(),
        input_index=0,
        proposal_id=uuid4(),
        file_id=uuid4(),
        filename="report.pdf",
        status=status,
        transaction_id=None,
        destination_path=None,
        reason_code=reason_code,
        reason=None,
    )


def test_ready_plan_item_is_info_with_no_suggested_action() -> None:
    message = es.plan_item_message(
        _plan_item(status=PlanStatus.READY, reason_code=None)
    )
    assert message.severity is Severity.INFO
    assert message.suggested_action is SuggestedAction.NONE
    assert message.title == "Listo para organizar"


def test_review_required_suggests_approve() -> None:
    message = es.plan_item_message(
        _plan_item(
            status=PlanStatus.REVIEW_REQUIRED,
            reason_code=PlanReasonCode.REVIEW_REQUIRED,
        )
    )
    assert message.severity is Severity.ATTENTION
    assert message.suggested_action is SuggestedAction.APPROVE


def test_conflict_suggests_review_conflict() -> None:
    message = es.plan_item_message(
        _plan_item(
            status=PlanStatus.CONFLICT, reason_code=PlanReasonCode.DESTINATION_OCCUPIED
        )
    )
    assert message.severity is Severity.ATTENTION
    assert message.suggested_action is SuggestedAction.REVIEW_CONFLICT


def test_invalid_and_blocked_are_errors() -> None:
    invalid = es.plan_item_message(
        _plan_item(
            status=PlanStatus.INVALID,
            reason_code=PlanReasonCode.AMBIGUOUS_REVIEW_HISTORY,
        )
    )
    blocked = es.plan_item_message(
        _plan_item(status=PlanStatus.BLOCKED, reason_code=PlanReasonCode.POLICY_BLOCK)
    )
    assert invalid.severity is Severity.ERROR
    assert blocked.severity is Severity.ERROR


def test_source_changed_reason_overrides_to_error_and_reanalyze() -> None:
    message = es.batch_item_message(
        _batch_item(
            status=BatchApplyItemStatus.NOT_APPLIED,
            reason_code="source_identity_changed",
        )
    )
    assert message.severity is Severity.ERROR
    assert message.suggested_action is SuggestedAction.REANALYZE


def test_applied_batch_item_is_info() -> None:
    message = es.batch_item_message(
        _batch_item(status=BatchApplyItemStatus.APPLIED, reason_code=None)
    )
    assert message.severity is Severity.INFO
    assert message.title == "Organizado"


def _batch_result(
    *, status: BatchStatus, applied: int, not_applied: int
) -> BatchApplyResult:
    selected = applied + not_applied
    return BatchApplyResult(
        batch_id=uuid4(),
        status=status,
        started_at=datetime.now(UTC),
        completed_at=None,
        requested_policy_decision_ids=tuple(uuid4() for _ in range(selected)),
        items=(),
        summary=BatchApplySummary(
            selected=selected,
            processed=selected,
            applied=applied,
            not_applied=not_applied,
            skipped=0,
            invalid=0,
        ),
        managed_root_id=uuid4(),
    )


def test_all_applied_batch_summary_is_positive_and_info() -> None:
    result = _batch_result(status=BatchStatus.COMPLETED, applied=3, not_applied=0)
    message = es.batch_summary_message(result)
    assert message.severity is Severity.INFO
    assert message.title == "3 archivos se organizaron correctamente."


def test_partial_batch_summary_mentions_both_counts() -> None:
    result = _batch_result(status=BatchStatus.COMPLETED, applied=2, not_applied=1)
    message = es.batch_summary_message(result)
    assert "2" in message.title
    assert "1" in message.title
    assert message.severity is Severity.ATTENTION


def test_nothing_applied_batch_summary_says_no_change() -> None:
    result = _batch_result(status=BatchStatus.COMPLETED, applied=0, not_applied=2)
    message = es.batch_summary_message(result)
    assert message.title == "No se realizó ningún cambio."


def test_incomplete_batch_summary_never_says_cancelada_or_falló() -> None:
    result = _batch_result(status=BatchStatus.INCOMPLETE, applied=1, not_applied=0)
    message = es.batch_summary_message(result)
    assert "cancelad" not in message.title.lower()
    assert "cancelad" not in message.detail.lower()
    assert "falló" not in message.title.lower()
    assert "falló" not in message.detail.lower()


def test_history_summary_message_matches_batch_summary_shape() -> None:
    entry = BatchHistoryEntry(
        batch_id=uuid4(),
        started_at=datetime.now(UTC),
        completed_at=None,
        status=BatchStatus.COMPLETED,
        requested_policy_decision_ids=(uuid4(), uuid4()),
        managed_root_id=uuid4(),
        selected_count=2,
        applied_count=2,
        not_applied_count=0,
        skipped_count=0,
        invalid_count=0,
        processed_count=2,
        items=None,
    )
    message = es.history_summary_message(entry)
    assert message.title == "2 archivos se organizaron correctamente."


def test_unavailable_history_row_message_never_fabricates_success() -> None:
    row = UnavailableBatchHistoryRow(
        batch_id=uuid4(), started_at=None, reason="malformed"
    )
    message = es.unavailable_history_row_message(row)
    assert message.severity is Severity.ERROR
    assert "organizaron" not in message.title.lower()
