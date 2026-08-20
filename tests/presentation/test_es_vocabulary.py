"""Spanish vocabulary coverage (FA-014 §22): every PlanStatus/
BatchApplyItemStatus has a label; rejection_reason_detail is total (never
raises, never falls through to an empty/English string) for every code this
codebase's rejection vocabularies define, plus for genuinely unknown/future
codes; no raw enum name or forbidden jargon term ever appears in rendered
copy."""

from pathlib import Path
from uuid import uuid4

from file_agent.application.dto import (
    ApplicationRejectionReason,
    BatchApplyItemResult,
    BatchApplyItemStatus,
)
from file_agent.application.errors import (
    AppDataManagedRootError,
    DuplicateManagedRootError,
    FilesystemRootManagedRootError,
    InvalidManagedRootPathError,
    ManagedRootReparsePointError,
    OverlappingManagedRootError,
    SystemDirectoryManagedRootError,
    UserProfileManagedRootError,
)
from file_agent.application.history import BatchHistoryItem
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootUnavailable,
)
from file_agent.application.organization_plan import PlanReasonCode, PlanStatus
from file_agent.domain import RejectionCode
from file_agent.presentation import es

FORBIDDEN_JARGON = (
    "policy_decision",
    "ExecutionAuthorization",
    "hash mismatch",
    "reparse point",
    "event payload",
    "canonical path",
    "containment",
    "root authority",
    "managed_root_id",
    "filesystem boundary",
    "ProtectedTree",
    "StructuralProtection",
    "marker",
    "hard exclusion",
    "scanner exclusion",
    "structural eligibility",
    "reparse",
    "authorization",
    "policy",
    "kind",
    # FA-017.3: the internal execution/history vocabulary this ticket
    # replaces with consumer Spanish -- never product-visible.
    "applied",
    "not_applied",
    "PlanStatus",
    "PolicyOutcome",
    "RejectionCode",
    "reason_code",
    "transaction",
)


def _registration_error_instances() -> list[Exception]:
    from pathlib import Path

    path = Path("C:/Users/Ana/Downloads").resolve()
    other_id = uuid4()
    return [
        DuplicateManagedRootError(path, other_id),
        OverlappingManagedRootError(path / "child", other_id, path),
        OverlappingManagedRootError(path, other_id, path / "child"),
        FilesystemRootManagedRootError(path, "drive root"),
        UserProfileManagedRootError(path, "user profile"),
        SystemDirectoryManagedRootError(path, "system directory"),
        AppDataManagedRootError(path, "app data overlap"),
        InvalidManagedRootPathError(path, "invalid"),
        ManagedRootReparsePointError(path, "reparse"),
    ]


def _all_rendered_strings() -> list[str]:
    strings: list[str] = []
    for status in PlanStatus:
        strings.append(es.plan_status_label(status))
    for status in BatchApplyItemStatus:
        strings.append(es.batch_item_status_label(status))
    for enum_cls in (ApplicationRejectionReason, PlanReasonCode, RejectionCode):
        for member in enum_cls:
            strings.append(es.rejection_reason_detail(member.value))
    strings.append(es.rejection_reason_detail(None))
    strings.append(es.rejection_reason_detail("some_future_unmapped_code"))

    for exc in _registration_error_instances():
        message = es.managed_root_registration_error_message(exc)
        strings.append(message.title)
        strings.append(message.detail)

    for status in ManagedRootLookupStatus:
        message = es.managed_root_unavailable_message(
            ManagedRootUnavailable(uuid4(), status, "detail")
        )
        strings.append(message.title)
        strings.append(message.detail)

    for message in (
        es.undo_historical_root_unavailable_message(),
        es.restore_historical_root_unavailable_message(),
    ):
        strings.append(message.title)
        strings.append(message.detail)

    from pathlib import Path

    from file_agent.structural_safety import (
        ProjectMarkerType,
        StructuralProtection,
        StructuralProtectionKind,
    )

    protected_tree_message = es.protected_trees_summary_message(
        [
            StructuralProtection(
                kind=StructuralProtectionKind.PROTECTED_TREE,
                root_path=Path("C:/Users/Ana/Downloads/project").resolve(),
                marker=ProjectMarkerType.PYPROJECT_TOML,
                marker_path=Path(
                    "C:/Users/Ana/Downloads/project/pyproject.toml"
                ).resolve(),
                excluded_name=None,
            )
        ]
    )
    assert protected_tree_message is not None
    strings.append(protected_tree_message.title)
    strings.append(protected_tree_message.detail)

    note = es.structural_protection_note(3)
    assert note is not None
    strings.append(note)

    from file_agent.application.destination_setup import (
        DestinationPreparationOutcome,
        DestinationPreparationStatus,
        DestinationSetupReasonCode,
    )
    from file_agent.domain import DestinationCategory

    for status, reason_code in (
        (DestinationPreparationStatus.PREPARED, None),
        (DestinationPreparationStatus.ALREADY_AVAILABLE, None),
        *(
            (DestinationPreparationStatus.NOT_PREPARED, reason)
            for reason in DestinationSetupReasonCode
        ),
    ):
        outcome = DestinationPreparationOutcome(
            DestinationCategory.DOCUMENTS, status, reason_code
        )
        message = es.destination_preparation_item_message(outcome)
        strings.append(message.title)
        strings.append(message.detail)

    def _outcome(
        status: DestinationPreparationStatus,
    ) -> DestinationPreparationOutcome:
        reason = (
            None
            if status is not DestinationPreparationStatus.NOT_PREPARED
            else DestinationSetupReasonCode.FILE_AT_DESTINATION
        )
        return DestinationPreparationOutcome(DestinationCategory.IMAGES, status, reason)

    for outcomes in (
        [_outcome(DestinationPreparationStatus.PREPARED)],
        [_outcome(DestinationPreparationStatus.ALREADY_AVAILABLE)],
        [
            _outcome(DestinationPreparationStatus.PREPARED),
            _outcome(DestinationPreparationStatus.ALREADY_AVAILABLE),
        ],
        [
            _outcome(DestinationPreparationStatus.PREPARED),
            _outcome(DestinationPreparationStatus.NOT_PREPARED),
        ],
    ):
        summary = es.destination_setup_summary_message(outcomes)
        strings.append(summary.title)
        strings.append(summary.detail)

    # FA-017.3: batch_item_result_message (execution) across every status x
    # every reason_code this codebase's three rejection vocabularies define
    # x both source_unchanged_confirmed values, plus history_item_message
    # (durable-only) across the same status/reason space.
    all_reason_codes: list[str | None] = [None]
    for enum_cls in (ApplicationRejectionReason, RejectionCode):
        all_reason_codes.extend(member.value for member in enum_cls)
    all_reason_codes.append("some_future_unmapped_code")

    for status in BatchApplyItemStatus:
        for reason_code in all_reason_codes:
            if status is BatchApplyItemStatus.APPLIED and reason_code is not None:
                continue  # APPLIED never carries a reason_code in practice
            item = BatchApplyItemResult(
                policy_decision_id=uuid4(),
                input_index=0,
                proposal_id=uuid4(),
                file_id=uuid4(),
                filename="report.pdf",
                status=status,
                transaction_id=uuid4(),
                source_path=Path("C:/sandbox/report.pdf"),
                destination_path=Path("C:/sandbox/Documents/report.pdf"),
                reason_code=reason_code,
                reason=None,
                source_unchanged_confirmed=True,
            )
            for confirmed in (True, False):
                message = es.batch_item_result_message(
                    item, source_unchanged_confirmed=confirmed
                )
                strings.append(message.title)
                strings.append(message.detail)

            history_item = BatchHistoryItem(
                policy_decision_id=uuid4(),
                input_index=0,
                status=status,
                transaction_id=uuid4(),
                reason_code=reason_code,
                filename="report.pdf",
                source_path=Path("C:/sandbox/report.pdf"),
                destination_path=Path("C:/sandbox/Documents/report.pdf"),
                undo_available=False,
            )
            history_message = es.history_item_message(history_item)
            strings.append(history_message.title)
            strings.append(history_message.detail)

    return strings


def test_every_plan_status_has_a_spanish_label() -> None:
    for status in PlanStatus:
        label = es.plan_status_label(status)
        assert label
        assert label.strip() == label


def test_every_batch_item_status_has_a_spanish_label() -> None:
    for status in BatchApplyItemStatus:
        label = es.batch_item_status_label(status)
        assert label
        assert label.strip() == label


def test_rejection_reason_detail_is_total_never_raises_never_empty() -> None:
    for enum_cls in (ApplicationRejectionReason, PlanReasonCode, RejectionCode):
        for member in enum_cls:
            detail = es.rejection_reason_detail(member.value)
            assert detail

    assert es.rejection_reason_detail(None)
    assert es.rejection_reason_detail("totally_unrecognized_future_code")


def test_unmapped_code_renders_the_safe_generic_fallback() -> None:
    fallback = es.rejection_reason_detail(None)
    assert fallback == es.rejection_reason_detail("brand_new_code_from_a_future_ticket")
    # FA-017.3: the fallback deliberately no longer claims "no change was
    # made" -- an unmapped code includes a FAILED apply's free-text
    # failure_reason, for which that claim is not guaranteed. The
    # unchanged/unconfirmed claim is composed separately by the caller.
    assert "no se realizó ningún cambio" not in fallback.lower()
    assert "no modificó" not in fallback.lower()


def test_no_forbidden_jargon_or_raw_enum_name_in_any_rendered_string() -> None:
    for text in _all_rendered_strings():
        for jargon in FORBIDDEN_JARGON:
            assert jargon not in text
        for status in PlanStatus:
            assert f"PlanStatus.{status.name}" not in text
        for status in BatchApplyItemStatus:
            assert f"BatchApplyItemStatus.{status.name}" not in text


def test_every_mapped_reason_produces_a_truthful_consumer_message() -> None:
    """No mapped reason ever renders empty, and English/PolicyOutcome-style
    identifiers never leak through (already checked exhaustively by
    test_no_forbidden_jargon_or_raw_enum_name_in_any_rendered_string --
    this is a focused, minimal-fixture-count smoke test of the two new
    composers specifically)."""
    item = BatchApplyItemResult(
        policy_decision_id=uuid4(),
        input_index=0,
        proposal_id=uuid4(),
        file_id=uuid4(),
        filename="report.pdf",
        status=BatchApplyItemStatus.NOT_APPLIED,
        transaction_id=uuid4(),
        source_path=Path("C:/sandbox/report.pdf"),
        destination_path=None,
        reason_code="policy_block",
        reason=None,
        source_unchanged_confirmed=True,
    )
    message = es.batch_item_result_message(item, source_unchanged_confirmed=True)
    assert message.title
    assert message.detail
    assert message.title.strip() == message.title
    assert message.detail.strip() == message.detail


def test_fallback_mapping_never_makes_an_unsupported_unchanged_claim() -> None:
    """The generic fallback (an unrecognized/free-text reason) must never
    itself assert the source was unchanged -- only a caller with actual
    evidence (source_unchanged_confirmed=True, or a recognized pre-commit
    reason_code) may add that sentence."""
    detail = es.rejection_reason_detail("totally_unrecognized_future_code")
    assert "no se modificó" not in detail.lower()
    assert "no pudimos confirmar el estado final" not in detail.lower()


def test_designated_product_contract_strings() -> None:
    """A small, explicitly-called-out set of exact-string checks -- not the
    entire vocabulary table, to avoid brittleness on ordinary copy edits."""
    assert es.plan_status_label(PlanStatus.READY) == "Listo para organizar"
    assert es.plan_status_label(PlanStatus.REVIEW_REQUIRED) == "Necesita tu revisión"
    assert es.batch_item_status_label(BatchApplyItemStatus.APPLIED) == "Organizado"
    assert (
        es.rejection_reason_detail(None)
        == "No pudimos completar esta acción de forma segura."
    )
