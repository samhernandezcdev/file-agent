"""Per-command request-parameter models -- input-only, the mirror image of
views.py's output-only View DTOs. Same camelCase wire convention (the
frontend's typed bridge sends these shapes verbatim). Parsing failures
(missing/wrong-typed field, an unparseable UUID) raise pydantic's own
ValidationError, which dispatcher.py maps to a terminal `ok: false,
kind: "invalid_params"` frame -- a fully-completed, unambiguous round trip,
never a transport-level failure."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ParamsModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ManagedRootsAddParams(ParamsModel):
    path: str
    """The one raw filesystem path anywhere in this protocol -- sourced
    only from the native folder picker on the frontend side."""


class ManagedRootsRemoveParams(ParamsModel):
    managed_root_id: UUID


class ManagedRootsListParams(ParamsModel):
    pass


class AnalysisRunParams(ParamsModel):
    managed_root_id: UUID


class AnalysisReanalyzeFileParams(ParamsModel):
    file_id: UUID


class PlanCreateParams(ParamsModel):
    policy_decision_ids: tuple[UUID, ...]


class ReviewActionParams(ParamsModel):
    policy_decision_id: UUID
    note: str | None = None


class ApplyItemParams(ParamsModel):
    policy_decision_id: UUID


class ApplyItemsParams(ParamsModel):
    policy_decision_ids: tuple[UUID, ...]


class HistoryGetBatchParams(ParamsModel):
    batch_id: UUID
    include_items: bool = False


class HistoryListRecentParams(ParamsModel):
    limit: int = 20


class RecoveryUndoTransactionParams(ParamsModel):
    transaction_id: UUID


class RecoveryRestoreCaptureParams(ParamsModel):
    capture_id: UUID
