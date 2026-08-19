"""FA-017.2: application.organization_plan.missing_destination_categories --
the single shared definition of "this category currently has a
destination_parent_missing conflict", reused by both PlanAttentionView's
aggregation and destination-setup's current-need authorization. Pure unit
tests, no service/filesystem fixtures needed."""

from pathlib import Path
from uuid import uuid4

from file_agent.application.organization_plan import (
    OrganizationPlanItem,
    PlanReasonCode,
    PlanStatus,
    missing_destination_categories,
)
from file_agent.domain import DestinationCategory, FileCategory, PolicyOutcome


def _item(
    *,
    status: PlanStatus,
    reason_code: PlanReasonCode | None,
    destination_category: DestinationCategory | None,
    filename: str = "file.bin",
) -> OrganizationPlanItem:
    return OrganizationPlanItem(
        file_id=uuid4(),
        proposal_id=uuid4(),
        policy_decision_id=uuid4(),
        source_path=Path(f"C:/sandbox/{filename}"),
        filename=filename,
        category=FileCategory.DOCUMENT,
        destination_category=destination_category,
        destination_path=(
            Path(f"C:/sandbox/x/{filename}")
            if destination_category is not None
            else None
        ),
        policy_outcome=PolicyOutcome.AUTO,
        human_review_outcome=None,
        status=status,
        reason_code=reason_code,
        reason="irrelevant prose, never rendered directly",
    )


def test_a_ready_item_targeting_documents_is_excluded() -> None:
    items = (
        _item(
            status=PlanStatus.READY,
            reason_code=None,
            destination_category=DestinationCategory.DOCUMENTS,
        ),
    )
    assert missing_destination_categories(items) == frozenset()


def test_b_review_required_executables_not_yet_approved_is_excluded() -> None:
    items = (
        _item(
            status=PlanStatus.REVIEW_REQUIRED,
            reason_code=PlanReasonCode.REVIEW_REQUIRED,
            destination_category=DestinationCategory.EXECUTABLES,
        ),
    )
    assert missing_destination_categories(items) == frozenset()


def test_c_destination_parent_missing_images_is_included() -> None:
    items = (
        _item(
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_category=DestinationCategory.IMAGES,
        ),
    )
    assert missing_destination_categories(items) == frozenset(
        {DestinationCategory.IMAGES}
    )


def test_d_mixed_statuses_returns_exactly_the_missing_destination_categories() -> None:
    items = (
        _item(
            status=PlanStatus.READY,
            reason_code=None,
            destination_category=DestinationCategory.DOCUMENTS,
        ),
        _item(
            status=PlanStatus.REVIEW_REQUIRED,
            reason_code=PlanReasonCode.REVIEW_REQUIRED,
            destination_category=DestinationCategory.EXECUTABLES,
        ),
        _item(
            status=PlanStatus.BLOCKED,
            reason_code=PlanReasonCode.POLICY_BLOCK,
            destination_category=DestinationCategory.CODE,
        ),
        _item(
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_category=DestinationCategory.IMAGES,
        ),
        _item(
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_category=DestinationCategory.AUDIO,
        ),
    )
    assert missing_destination_categories(items) == frozenset(
        {DestinationCategory.IMAGES, DestinationCategory.AUDIO}
    )


def test_conflict_with_a_different_reason_code_is_excluded() -> None:
    items = (
        _item(
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_OCCUPIED,
            destination_category=DestinationCategory.DOCUMENTS,
        ),
    )
    assert missing_destination_categories(items) == frozenset()


def test_item_with_no_destination_category_never_appears() -> None:
    items = (
        _item(
            status=PlanStatus.CONFLICT,
            reason_code=PlanReasonCode.DESTINATION_PARENT_MISSING,
            destination_category=None,
        ),
    )
    assert missing_destination_categories(items) == frozenset()
