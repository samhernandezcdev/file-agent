"""Presentation-ready View DTOs -- the ONLY shapes the desktop frontend ever
receives. Pydantic models (not the internal frozen dataclasses in
application/dto.py etc.) because these are the wire contract:
`model_json_schema()` drives generated TypeScript types
(packages/desktop-types), and every field name is camelCased for the
frontend via `alias_generator`.

Never expose an internal authorization/domain object as transport
authority: no PolicyDecision, ExecutionAuthorization, TransactionRequest,
SandboxRoot, StructuralProtection, raw root path used as authorization, or
safe=true/ready=true/authorized=true flag anywhere below. Every mutating
follow-up action (approve/skip/apply/undo/restore) is driven by a stable,
previously-issued UUID the frontend echoes back -- never a client-computed
claim about safety.

Spanish copy is sourced from file_agent.presentation.es wherever the
corresponding application-layer decision has a message there -- this
module does not invent new user-facing prose; it renders what the trusted
decision already is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from file_agent.application import queries
from file_agent.application.destination_setup import (
    DestinationPreparationOutcome,
    DestinationSetupResult,
)
from file_agent.application.dto import (
    AnalysisFailure,
    AnalyzedItem,
    AnalyzedScanResult,
    ApplicationOutcomeStatus,
    ApplyResult,
    BatchApplyItemResult,
    BatchApplyResult,
    RestoreResult,
    ReviewActionResult,
    UndoResult,
)
from file_agent.application.errors import ManagedRootRegistrationError
from file_agent.application.history import BatchHistoryEntry, UnavailableBatchHistoryRow
from file_agent.application.managed_roots import (
    ManagedRootActionStatus,
    ManagedRootUnavailable,
    RemoveManagedRootResult,
)
from file_agent.application.managed_roots import (
    ManagedRootView as _ManagedRootDTO,
)
from file_agent.application.organization_plan import (
    OrganizationPlan,
    OrganizationPlanItem,
    PlanReasonCode,
    PlanStatus,
    missing_destination_categories,
)
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import DestinationCategory, FileCategory
from file_agent.presentation import es
from file_agent.presentation.messages import UserMessage as _UserMessage

# --- Spanish label tables (product-facing category names only; never a raw
# enum member name -- matches presentation/es.py's own convention) ----------

_FILE_CATEGORY_LABEL: dict[FileCategory, str] = {
    FileCategory.DOCUMENT: "Documento",
    FileCategory.IMAGE: "Imagen",
    FileCategory.AUDIO: "Audio",
    FileCategory.VIDEO: "Video",
    FileCategory.ARCHIVE: "Archivo comprimido",
    FileCategory.CODE: "Código",
    FileCategory.EXECUTABLE: "Programa",
    FileCategory.OTHER: "Otro",
    FileCategory.UNKNOWN: "Sin clasificar",
}

_DESTINATION_CATEGORY_LABEL: dict[DestinationCategory, str] = {
    DestinationCategory.DOCUMENTS: "Documentos",
    DestinationCategory.IMAGES: "Imágenes",
    DestinationCategory.AUDIO: "Audio",
    DestinationCategory.VIDEO: "Video",
    DestinationCategory.ARCHIVES: "Archivos comprimidos",
    DestinationCategory.CODE: "Código",
    DestinationCategory.EXECUTABLES: "Programas",
}


def _file_category_label(category: FileCategory) -> str:
    return _FILE_CATEGORY_LABEL.get(category, "Sin clasificar")


def _destination_category_label(category: DestinationCategory | None) -> str | None:
    if category is None:
        return None
    return _DESTINATION_CATEGORY_LABEL.get(category, category.value)


# --- Base model --------------------------------------------------------------


class ViewModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True
    )


class UserMessageView(ViewModel):
    title: str
    detail: str
    severity: str
    suggested_action: str


def _message_view(message: _UserMessage) -> UserMessageView:
    return UserMessageView(
        title=message.title,
        detail=message.detail,
        severity=message.severity.value,
        suggested_action=message.suggested_action.value,
    )


def _generic_rejection_message(title: str, reason_code: str | None) -> UserMessageView:
    return UserMessageView(
        title=title,
        detail=es.rejection_reason_detail(reason_code),
        severity="error",
        suggested_action="none",
    )


# --- Managed roots -------------------------------------------------------


class ManagedRootView(ViewModel):
    id: UUID
    display_path: str
    status: Literal["available", "unavailable"]


def managed_root_view(dto: _ManagedRootDTO) -> ManagedRootView:
    return ManagedRootView(
        id=dto.id, display_path=str(dto.path), status=dto.status.value
    )


class ManagedRootListView(ViewModel):
    roots: tuple[ManagedRootView, ...]


def managed_root_list_view(roots: tuple[_ManagedRootDTO, ...]) -> ManagedRootListView:
    return ManagedRootListView(roots=tuple(managed_root_view(r) for r in roots))


class RemoveManagedRootResultView(ViewModel):
    managed_root_id: UUID
    status: Literal["succeeded", "rejected"]
    message: UserMessageView | None


def remove_managed_root_result_view(
    result: RemoveManagedRootResult,
) -> RemoveManagedRootResultView:
    message = None
    if result.status is ManagedRootActionStatus.REJECTED:
        message = _generic_rejection_message(
            "No se pudo dejar de organizar esta carpeta.", result.reason_code
        )
    return RemoveManagedRootResultView(
        managed_root_id=result.managed_root_id,
        status=result.status.value,
        message=message,
    )


def managed_root_registration_error_view(
    exc: ManagedRootRegistrationError,
) -> UserMessageView:
    return _message_view(es.managed_root_registration_error_message(exc))


def managed_root_unavailable_view(
    unavailable: ManagedRootUnavailable,
) -> UserMessageView:
    return _message_view(es.managed_root_unavailable_message(unavailable))


class ManagedRootUnavailableResultView(ViewModel):
    """The `outcome` discriminant shared by every command whose
    FileAgentApplicationService method can return ManagedRootUnavailable
    instead of its normal result -- analysis.run, plan.create, apply.items.
    Not an exception/transport error: a legitimate, expected business
    outcome, delivered as a normal `ok: true` terminal frame like any
    other result."""

    outcome: Literal["managed_root_unavailable"]
    message: UserMessageView


def managed_root_unavailable_result_view(
    unavailable: ManagedRootUnavailable,
) -> ManagedRootUnavailableResultView:
    return ManagedRootUnavailableResultView(
        outcome="managed_root_unavailable",
        message=managed_root_unavailable_view(unavailable),
    )


# --- Analysis --------------------------------------------------------------


class AnalyzedItemView(ViewModel):
    file_id: UUID
    filename: str
    source_display_path: str
    category_label: str
    proposed_destination_category_label: str | None
    policy_decision_id: UUID
    requires_review: bool
    confidence: float


def analyzed_item_view(item: AnalyzedItem) -> AnalyzedItemView:
    return AnalyzedItemView(
        file_id=item.file_id,
        filename=item.filename,
        source_display_path=str(item.path),
        category_label=_file_category_label(item.category),
        proposed_destination_category_label=_destination_category_label(
            item.proposed_destination_category
        ),
        policy_decision_id=item.policy_decision_id,
        requires_review=item.requires_review,
        confidence=item.confidence,
    )


class AnalysisFailureView(ViewModel):
    file_id: UUID
    source_display_path: str | None
    message: UserMessageView


def analysis_failure_view(failure: AnalysisFailure) -> AnalysisFailureView:
    return AnalysisFailureView(
        file_id=failure.file_id,
        source_display_path=str(failure.path) if failure.path is not None else None,
        message=_generic_rejection_message(
            "No se pudo analizar este archivo.", failure.reason_code
        ),
    )


class AnalysisResultView(ViewModel):
    outcome: Literal["ok"]
    scan_id: UUID
    items: tuple[AnalyzedItemView, ...]
    failures: tuple[AnalysisFailureView, ...]
    files_discovered: int
    protected_trees_message: UserMessageView | None


def analysis_result_view(result: AnalyzedScanResult) -> AnalysisResultView:
    protected_message = es.protected_trees_summary_message(result.protected_trees)
    return AnalysisResultView(
        outcome="ok",
        scan_id=result.scan_id,
        items=tuple(analyzed_item_view(i) for i in result.items),
        failures=tuple(analysis_failure_view(f) for f in result.failures),
        files_discovered=result.files_discovered,
        protected_trees_message=(
            _message_view(protected_message) if protected_message is not None else None
        ),
    )


# --- Organization plan (preview) --------------------------------------------


class PlanItemView(ViewModel):
    action_id: UUID
    """policy_decision_id -- the one stable id apply/review actions echo
    back. Never a path, never a caller-computed authorization claim."""
    filename: str
    source_display_path: str
    destination_display_path: str | None
    category_label: str
    status: str
    title: str
    detail: str
    severity: str
    selectable: bool
    """True only when status is READY -- the sole case the frontend may
    offer a checkbox for. Review items get Aprobar/Omitir instead; every
    other status is informational-only, never client-side inferred."""
    needs_review_action: bool
    """FA-017.3. True only when status is REVIEW_REQUIRED -- the sole case
    the frontend may offer Aprobar/Omitir for. A pure function of status,
    computed here (not client-side) so React never compares the raw status
    string itself, exactly mirroring selectable's own existing role for
    READY."""


def plan_item_view(item: OrganizationPlanItem) -> PlanItemView:
    message = es.plan_item_message(item)
    return PlanItemView(
        action_id=item.policy_decision_id,
        filename=item.filename,
        source_display_path=str(item.source_path),
        destination_display_path=(
            str(item.destination_path) if item.destination_path is not None else None
        ),
        category_label=_file_category_label(item.category),
        status=item.status.value,
        title=message.title,
        detail=message.detail,
        severity=message.severity.value,
        selectable=item.status is PlanStatus.READY,
        needs_review_action=item.status is PlanStatus.REVIEW_REQUIRED,
    )


class PlanAttentionView(ViewModel):
    """FA-017.1 §18: an additive, presentation-owned aggregation over items
    that share the same underlying blocker -- computed here so React never
    branches on `reason_code` itself (which never appears on this DTO, or
    anywhere else on the wire)."""

    variant: Literal["missing_destination_folder"]
    """Presentation-owned, closed, template-selection ONLY. Not derived
    from, and not a proxy for, reason_code."""
    category_label: str
    """Matches PlanItemView.categoryLabel -- tells React which PlanGroup to
    render this above. A pure lookup key, not a semantic field."""
    destination_label: str
    """The literal, real folder name the user must create (e.g.
    "Documents") -- shown verbatim, like any other real filesystem name
    already surfaced elsewhere. Not translated: it is data, not
    vocabulary."""
    destination_category: DestinationCategory
    """FA-017.2: the real, machine-stable wire identity a
    destination_setup.prepare request echoes back -- a closed 7-member
    enum, never a path, never derived from destination_label (which is
    display text only, not designed as a protocol identifier even though
    it happens to equal the physical folder name today)."""
    message: UserMessageView
    affected_filenames: tuple[str, ...]


def _missing_destination_folder_attentions(
    items: tuple[OrganizationPlanItem, ...],
) -> tuple[PlanAttentionView, ...]:
    """Groups CONFLICT items whose reason is DESTINATION_PARENT_MISSING by
    destination_category. Which categories get an entry at all comes from
    the single shared missing_destination_categories() definition
    (FA-017.2 -- also used by destination-setup's current-need
    authorization, application/service.py::prepare_destinations) -- this
    loop only assigns each qualifying item to its already-known bucket, so
    the two call sites can never independently drift on what "missing"
    means."""
    required = missing_destination_categories(items)
    groups: dict[DestinationCategory, list[OrganizationPlanItem]] = {
        category: [] for category in required
    }
    for item in items:
        if (
            item.destination_category not in required
            or item.status is not PlanStatus.CONFLICT
            or item.reason_code is not PlanReasonCode.DESTINATION_PARENT_MISSING
            or item.destination_path is None
        ):
            continue
        groups[item.destination_category].append(item)

    attentions: list[PlanAttentionView] = []
    for category, group_items in groups.items():
        if not group_items:
            continue
        first = group_items[0]
        assert first.destination_path is not None  # guaranteed by the filter above
        destination_label = first.destination_path.parent.name
        attentions.append(
            PlanAttentionView(
                variant="missing_destination_folder",
                category_label=_file_category_label(first.category),
                destination_label=destination_label,
                destination_category=category,
                message=_message_view(
                    es.missing_destination_folder_message(
                        _file_category_label(first.category),
                        destination_label,
                        len(group_items),
                    )
                ),
                affected_filenames=tuple(i.filename for i in group_items),
            )
        )
    return tuple(attentions)


class PlanSummaryView(ViewModel):
    files_total: int
    ready: int
    review_required: int
    conflicts: int
    invalid: int
    blocked: int
    skipped: int
    no_action: int
    protected: int
    issues: int


class PlanView(ViewModel):
    outcome: Literal["ok"]
    id: UUID
    managed_root_id: UUID | None
    root_display_path: str | None
    items: tuple[PlanItemView, ...]
    attentions: tuple[PlanAttentionView, ...]
    """FA-017.1 §18: additive-only aggregation over `items` the planner
    already produced -- computed here, never derived by React from
    reason_code (which is never exposed on the wire)."""
    summary: PlanSummaryView
    structural_protection_note: str | None


def plan_view(plan: OrganizationPlan) -> PlanView:
    summary = plan.summary
    return PlanView(
        outcome="ok",
        id=plan.id,
        managed_root_id=plan.managed_root_id,
        root_display_path=str(plan.root_path) if plan.root_path is not None else None,
        items=tuple(plan_item_view(i) for i in plan.items),
        attentions=_missing_destination_folder_attentions(plan.items),
        summary=PlanSummaryView(
            files_total=summary.files_total,
            ready=summary.ready,
            review_required=summary.review_required,
            conflicts=summary.conflicts,
            invalid=summary.invalid,
            blocked=summary.blocked,
            skipped=summary.skipped,
            no_action=summary.no_action,
            protected=summary.protected,
            issues=summary.issues,
        ),
        structural_protection_note=es.structural_protection_note(summary.protected),
    )


# --- Destination setup (FA-017.2) --------------------------------------------


class DestinationSetupItemResultView(ViewModel):
    destination_category: DestinationCategory
    destination_label: str
    """The literal physical folder name (e.g. "Documents") -- rendered
    verbatim, same convention as PlanAttentionView.destination_label."""
    status: Literal["prepared", "already_available", "not_prepared"]
    message: UserMessageView


def _destination_setup_item_result_view(
    outcome: DestinationPreparationOutcome,
) -> DestinationSetupItemResultView:
    return DestinationSetupItemResultView(
        destination_category=outcome.destination_category,
        destination_label=PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY[
            outcome.destination_category
        ],
        status=outcome.status.value,
        message=_message_view(es.destination_preparation_item_message(outcome)),
    )


class DestinationSetupResultView(ViewModel):
    outcome: Literal["ok"]
    setup_id: UUID
    managed_root_id: UUID
    items: tuple[DestinationSetupItemResultView, ...]
    summary_message: UserMessageView


def destination_setup_result_view(
    result: DestinationSetupResult,
) -> DestinationSetupResultView:
    return DestinationSetupResultView(
        outcome="ok",
        setup_id=result.setup_id,
        managed_root_id=result.managed_root_id,
        items=tuple(_destination_setup_item_result_view(o) for o in result.outcomes),
        summary_message=_message_view(
            es.destination_setup_summary_message(result.outcomes)
        ),
    )


# --- Review ------------------------------------------------------------------


class ReviewActionResultView(ViewModel):
    policy_decision_id: UUID
    status: Literal["succeeded", "rejected"]
    message: UserMessageView | None


def review_action_result_view(result: ReviewActionResult) -> ReviewActionResultView:
    message = None
    if result.status is ApplicationOutcomeStatus.REJECTED:
        message = _generic_rejection_message(
            "No se pudo registrar tu decisión.", result.reason_code
        )
    return ReviewActionResultView(
        policy_decision_id=result.policy_decision_id,
        status=result.status.value,
        message=message,
    )


# --- Apply -------------------------------------------------------------------

_APPLY_STATUS_TITLE: dict[ApplicationOutcomeStatus, str] = {
    ApplicationOutcomeStatus.REJECTED: "No se movió este archivo.",
    ApplicationOutcomeStatus.FAILED: "No pudimos organizar este archivo.",
}


class ApplyResultView(ViewModel):
    policy_decision_id: UUID
    transaction_id: UUID | None
    status: Literal["succeeded", "rejected", "failed"]
    destination_display_path: str | None
    message: UserMessageView | None


def apply_result_view(result: ApplyResult) -> ApplyResultView:
    message = None
    if result.status is not ApplicationOutcomeStatus.SUCCEEDED:
        message = _generic_rejection_message(
            _APPLY_STATUS_TITLE[result.status], result.reason_code
        )
    return ApplyResultView(
        policy_decision_id=result.policy_decision_id,
        transaction_id=result.transaction_id,
        status=result.status.value,
        destination_display_path=(
            str(result.destination_path)
            if result.destination_path is not None
            else None
        ),
        message=message,
    )


class BatchApplyItemResultView(ViewModel):
    policy_decision_id: UUID
    input_index: int
    filename: str | None
    status: str
    transaction_id: UUID | None
    source_display_path: str | None
    destination_display_path: str | None
    message: UserMessageView
    source_unchanged_confirmed: bool
    """FA-017.3. See application.dto.BatchApplyItemResult's field of the
    same name for full semantics -- ephemeral, execution-time-only, never
    product-relevant for an APPLIED result (React must not render it
    there)."""


def batch_apply_item_result_view(
    item: BatchApplyItemResult,
) -> BatchApplyItemResultView:
    return BatchApplyItemResultView(
        policy_decision_id=item.policy_decision_id,
        input_index=item.input_index,
        filename=item.filename,
        status=item.status.value,
        transaction_id=item.transaction_id,
        source_display_path=(
            str(item.source_path) if item.source_path is not None else None
        ),
        destination_display_path=(
            str(item.destination_path) if item.destination_path is not None else None
        ),
        message=_message_view(
            es.batch_item_result_message(
                item, source_unchanged_confirmed=item.source_unchanged_confirmed
            )
        ),
        source_unchanged_confirmed=item.source_unchanged_confirmed,
    )


class BatchApplySummaryView(ViewModel):
    selected: int
    processed: int
    applied: int
    not_applied: int
    skipped: int
    invalid: int


class BatchApplyResultView(ViewModel):
    outcome: Literal["ok"]
    batch_id: UUID
    status: Literal["completed", "incomplete"]
    started_at: datetime
    completed_at: datetime | None
    managed_root_id: UUID | None
    items: tuple[BatchApplyItemResultView, ...]
    summary: BatchApplySummaryView
    summary_message: UserMessageView


def batch_apply_result_view(result: BatchApplyResult) -> BatchApplyResultView:
    summary = result.summary
    return BatchApplyResultView(
        outcome="ok",
        batch_id=result.batch_id,
        status=result.status.value,
        started_at=result.started_at,
        completed_at=result.completed_at,
        managed_root_id=result.managed_root_id,
        items=tuple(batch_apply_item_result_view(i) for i in result.items),
        summary=BatchApplySummaryView(
            selected=summary.selected,
            processed=summary.processed,
            applied=summary.applied,
            not_applied=summary.not_applied,
            skipped=summary.skipped,
            invalid=summary.invalid,
        ),
        summary_message=_message_view(es.batch_summary_message(result)),
    )


# --- History -----------------------------------------------------------------


class BatchHistoryItemView(ViewModel):
    policy_decision_id: UUID
    input_index: int
    status: str
    transaction_id: UUID | None
    reason_detail: str | None
    filename: str | None
    """FA-017.3. None only when neither a resolved transaction nor a
    durable discovery record (via file_id) is available -- honest
    absence, never guessed. See application.history.BatchHistoryItem."""
    source_display_path: str | None
    destination_display_path: str | None
    undo_available: bool
    """FA-017.3. Durable evidence permits offering Deshacer -- never a
    guarantee. See application.history.BatchHistoryItem's field of the
    same name."""
    message: UserMessageView


class BatchHistoryEntryView(ViewModel):
    row_type: Literal["entry"]
    outcome: Literal["found"]
    batch_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: Literal["completed", "incomplete"]
    selected_count: int
    applied_count: int
    not_applied_count: int
    skipped_count: int
    invalid_count: int
    processed_count: int
    managed_root_id: UUID | None
    items: tuple[BatchHistoryItemView, ...] | None
    summary_message: UserMessageView


def batch_history_entry_view(entry: BatchHistoryEntry) -> BatchHistoryEntryView:
    items = None
    if entry.items is not None:
        items = tuple(
            BatchHistoryItemView(
                policy_decision_id=i.policy_decision_id,
                input_index=i.input_index,
                status=i.status.value,
                transaction_id=i.transaction_id,
                reason_detail=(
                    es.rejection_reason_detail(i.reason_code)
                    if i.reason_code is not None
                    else None
                ),
                filename=i.filename,
                source_display_path=(
                    str(i.source_path) if i.source_path is not None else None
                ),
                destination_display_path=(
                    str(i.destination_path) if i.destination_path is not None else None
                ),
                undo_available=i.undo_available,
                message=_message_view(es.history_item_message(i)),
            )
            for i in entry.items
        )
    return BatchHistoryEntryView(
        row_type="entry",
        outcome="found",
        batch_id=entry.batch_id,
        started_at=entry.started_at,
        completed_at=entry.completed_at,
        status=entry.status.value,
        selected_count=entry.selected_count,
        applied_count=entry.applied_count,
        not_applied_count=entry.not_applied_count,
        skipped_count=entry.skipped_count,
        invalid_count=entry.invalid_count,
        processed_count=entry.processed_count,
        managed_root_id=entry.managed_root_id,
        items=items,
        summary_message=_message_view(es.history_summary_message(entry)),
    )


class UnavailableBatchHistoryRowView(ViewModel):
    row_type: Literal["unavailable"]
    batch_id: UUID
    started_at: datetime | None
    message: UserMessageView


def unavailable_batch_history_row_view(
    row: UnavailableBatchHistoryRow,
) -> UnavailableBatchHistoryRowView:
    return UnavailableBatchHistoryRowView(
        row_type="unavailable",
        batch_id=row.batch_id,
        started_at=row.started_at,
        message=_message_view(es.unavailable_history_row_message(row)),
    )


def batch_history_row_view(
    row: BatchHistoryEntry | UnavailableBatchHistoryRow,
) -> BatchHistoryEntryView | UnavailableBatchHistoryRowView:
    if isinstance(row, BatchHistoryEntry):
        return batch_history_entry_view(row)
    return unavailable_batch_history_row_view(row)


class RecentHistoryView(ViewModel):
    rows: tuple[BatchHistoryEntryView | UnavailableBatchHistoryRowView, ...]


class HistoryLookupFailureView(ViewModel):
    outcome: Literal["unavailable"]
    message: UserMessageView


def history_lookup_failure_view(
    failure: queries.LookupFailure,
) -> HistoryLookupFailureView:
    return HistoryLookupFailureView(
        outcome="unavailable",
        message=UserMessageView(
            title="No pudimos mostrar los detalles de esta operación.",
            detail=es.rejection_reason_detail(None),
            severity="error",
            suggested_action="none",
        ),
    )


# --- Undo / restore ----------------------------------------------------------


class UndoResultView(ViewModel):
    transaction_id: UUID
    recovery_id: UUID | None
    status: Literal["succeeded", "rejected", "failed"]
    restored_display_path: str | None
    message: UserMessageView | None


def undo_result_view(result: UndoResult) -> UndoResultView:
    message = None
    if result.status is not ApplicationOutcomeStatus.SUCCEEDED:
        if result.reason_code == "historical_root_unavailable":
            message = _message_view(es.undo_historical_root_unavailable_message())
        else:
            message = _generic_rejection_message(
                "No pudimos deshacer este cambio.", result.reason_code
            )
    return UndoResultView(
        transaction_id=result.transaction_id,
        recovery_id=result.recovery_id,
        status=result.status.value,
        restored_display_path=(
            str(result.restored_path) if result.restored_path is not None else None
        ),
        message=message,
    )


class RestoreResultView(ViewModel):
    capture_id: UUID
    recovery_id: UUID | None
    status: Literal["succeeded", "rejected", "failed"]
    restored_display_path: str | None
    message: UserMessageView | None


def restore_result_view(result: RestoreResult) -> RestoreResultView:
    message = None
    if result.status is not ApplicationOutcomeStatus.SUCCEEDED:
        if result.reason_code == "historical_root_unavailable":
            message = _message_view(es.restore_historical_root_unavailable_message())
        else:
            message = _generic_rejection_message(
                "No pudimos restaurar este archivo.", result.reason_code
            )
    return RestoreResultView(
        capture_id=result.capture_id,
        recovery_id=result.recovery_id,
        status=result.status.value,
        restored_display_path=(
            str(result.restored_path) if result.restored_path is not None else None
        ),
        message=message,
    )
