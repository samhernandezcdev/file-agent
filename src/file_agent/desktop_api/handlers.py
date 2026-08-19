"""The 15 closed command handlers. Every handler calls exactly one
FileAgentApplicationService public method (or, for read-model queries, the
same public API surface) and maps its result through views.py -- never
managed_fs, never TransactionEngine/RecoveryEngine internals, never
SandboxRoot/ExecutionAuthorization construction, never raw persistence
mutation. See tests/desktop_api/test_dependency_boundary.py for the AST
guardrail enforcing this statically, mirroring
tests/application/test_mutation_boundary.py's own established pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from file_agent.application import FileAgentApplicationService
from file_agent.application.dto import AnalysisFailure
from file_agent.application.errors import TerminalPersistenceError
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.application.queries import LookupFailure
from file_agent.desktop_api import params as p
from file_agent.desktop_api import views as v


def handle_managed_roots_add(
    service: FileAgentApplicationService, params: p.ManagedRootsAddParams
) -> v.ManagedRootView:
    return v.managed_root_view(service.add_managed_root(Path(params.path)))


def handle_managed_roots_remove(
    service: FileAgentApplicationService, params: p.ManagedRootsRemoveParams
) -> v.RemoveManagedRootResultView:
    return v.remove_managed_root_result_view(
        service.remove_managed_root(params.managed_root_id)
    )


def handle_managed_roots_list(
    service: FileAgentApplicationService, params: p.ManagedRootsListParams
) -> v.ManagedRootListView:
    return v.managed_root_list_view(service.list_managed_roots())


def handle_analysis_run(
    service: FileAgentApplicationService, params: p.AnalysisRunParams
) -> v.AnalysisResultView | v.ManagedRootUnavailableResultView:
    result = service.analyze_managed_root(params.managed_root_id)
    if isinstance(result, ManagedRootUnavailable):
        return v.managed_root_unavailable_result_view(result)
    return v.analysis_result_view(result)


def handle_analysis_reanalyze_file(
    service: FileAgentApplicationService, params: p.AnalysisReanalyzeFileParams
) -> v.AnalyzedItemView | v.AnalysisFailureView:
    result = service.analyze_file(params.file_id)
    if isinstance(result, AnalysisFailure):
        return v.analysis_failure_view(result)
    return v.analyzed_item_view(result)


def handle_plan_create(
    service: FileAgentApplicationService, params: p.PlanCreateParams
) -> v.PlanView | v.ManagedRootUnavailableResultView:
    result = service.create_organization_plan(list(params.policy_decision_ids))
    if isinstance(result, ManagedRootUnavailable):
        return v.managed_root_unavailable_result_view(result)
    return v.plan_view(result)


def handle_review_approve(
    service: FileAgentApplicationService, params: p.ReviewActionParams
) -> v.ReviewActionResultView:
    return v.review_action_result_view(
        service.approve_review(params.policy_decision_id, note=params.note)
    )


def handle_review_skip(
    service: FileAgentApplicationService, params: p.ReviewActionParams
) -> v.ReviewActionResultView:
    return v.review_action_result_view(
        service.skip_review(params.policy_decision_id, note=params.note)
    )


def handle_apply_item(
    service: FileAgentApplicationService, params: p.ApplyItemParams
) -> v.ApplyResultView:
    try:
        result = service.apply_item(params.policy_decision_id)
    except TerminalPersistenceError as exc:
        # The mutation genuinely completed; only its own audit event failed
        # to persist. Render the real, already-computed outcome -- never a
        # fabricated REJECTED/FAILED status. This is an in-process Python
        # certainty, unrelated to the desktop transport's own UNKNOWN
        # semantics (which apply only when the SIDECAR CONNECTION itself is
        # lost -- see protocol.py/RetrySafety).
        result = exc.result  # type: ignore[assignment]
    return v.apply_result_view(result)


def handle_apply_items(
    service: FileAgentApplicationService, params: p.ApplyItemsParams
) -> v.BatchApplyResultView | v.ManagedRootUnavailableResultView:
    result = service.apply_items(list(params.policy_decision_ids))
    if isinstance(result, ManagedRootUnavailable):
        return v.managed_root_unavailable_result_view(result)
    return v.batch_apply_result_view(result)


def handle_history_get_batch(
    service: FileAgentApplicationService, params: p.HistoryGetBatchParams
) -> v.BatchHistoryEntryView | v.HistoryLookupFailureView:
    result = service.get_batch_history(
        params.batch_id, include_items=params.include_items
    )
    if isinstance(result, LookupFailure):
        return v.history_lookup_failure_view(result)
    return v.batch_history_entry_view(result)


def handle_history_list_recent(
    service: FileAgentApplicationService, params: p.HistoryListRecentParams
) -> v.RecentHistoryView:
    rows = service.list_recent_batch_history(limit=params.limit)
    return v.RecentHistoryView(rows=tuple(v.batch_history_row_view(r) for r in rows))


def handle_recovery_undo_transaction(
    service: FileAgentApplicationService, params: p.RecoveryUndoTransactionParams
) -> v.UndoResultView:
    try:
        result = service.undo_transaction(params.transaction_id)
    except TerminalPersistenceError as exc:
        result = exc.result  # type: ignore[assignment]
    return v.undo_result_view(result)


def handle_recovery_restore_capture(
    service: FileAgentApplicationService, params: p.RecoveryRestoreCaptureParams
) -> v.RestoreResultView:
    try:
        result = service.restore_capture(params.capture_id)
    except TerminalPersistenceError as exc:
        result = exc.result  # type: ignore[assignment]
    return v.restore_result_view(result)


def handle_destination_setup_prepare(
    service: FileAgentApplicationService, params: p.DestinationSetupPrepareParams
) -> v.DestinationSetupResultView | v.ManagedRootUnavailableResultView:
    result = service.prepare_destinations(
        params.managed_root_id, list(params.destination_categories)
    )
    if isinstance(result, ManagedRootUnavailable):
        return v.managed_root_unavailable_result_view(result)
    return v.destination_setup_result_view(result)


class _HandlerEntry:
    __slots__ = ("handler", "params_model")

    def __init__(
        self,
        params_model: type[p.ParamsModel],
        handler: Callable[[FileAgentApplicationService, Any], BaseModel],
    ) -> None:
        self.params_model = params_model
        self.handler = handler


HANDLERS: dict[str, _HandlerEntry] = {
    "managed_roots.add": _HandlerEntry(
        p.ManagedRootsAddParams, handle_managed_roots_add
    ),
    "managed_roots.remove": _HandlerEntry(
        p.ManagedRootsRemoveParams, handle_managed_roots_remove
    ),
    "managed_roots.list": _HandlerEntry(
        p.ManagedRootsListParams, handle_managed_roots_list
    ),
    "analysis.run": _HandlerEntry(p.AnalysisRunParams, handle_analysis_run),
    "analysis.reanalyze_file": _HandlerEntry(
        p.AnalysisReanalyzeFileParams, handle_analysis_reanalyze_file
    ),
    "plan.create": _HandlerEntry(p.PlanCreateParams, handle_plan_create),
    "review.approve": _HandlerEntry(p.ReviewActionParams, handle_review_approve),
    "review.skip": _HandlerEntry(p.ReviewActionParams, handle_review_skip),
    "apply.item": _HandlerEntry(p.ApplyItemParams, handle_apply_item),
    "apply.items": _HandlerEntry(p.ApplyItemsParams, handle_apply_items),
    "history.get_batch": _HandlerEntry(
        p.HistoryGetBatchParams, handle_history_get_batch
    ),
    "history.list_recent": _HandlerEntry(
        p.HistoryListRecentParams, handle_history_list_recent
    ),
    "recovery.undo_transaction": _HandlerEntry(
        p.RecoveryUndoTransactionParams, handle_recovery_undo_transaction
    ),
    "recovery.restore_capture": _HandlerEntry(
        p.RecoveryRestoreCaptureParams, handle_recovery_restore_capture
    ),
    "destination_setup.prepare": _HandlerEntry(
        p.DestinationSetupPrepareParams, handle_destination_setup_prepare
    ),
}
