"""Spanish product-messaging string tables and pure translation functions
(FA-014). One-directional: this module imports from application/domain, and
nothing in application/domain/destination/any engine ever imports this
module (enforced by tests/application/test_mutation_boundary.py's own
import-direction style guardrail, extended for presentation/).

Every function here is total: an unmapped/future code always renders the
safe generic fallback (never raises, never shows an empty/English string).
Rendering happens strictly after a decision is already final -- nothing
here ever feeds back into authorization or control flow, and no Spanish
string is ever added to a domain enum or engine.
"""

from file_agent.application.dto import (
    BatchApplyItemResult,
    BatchApplyItemStatus,
    BatchApplyResult,
    BatchStatus,
)
from file_agent.application.errors import (
    AppDataManagedRootError,
    DuplicateManagedRootError,
    FilesystemRootManagedRootError,
    InvalidManagedRootPathError,
    ManagedRootRegistrationError,
    ManagedRootReparsePointError,
    OverlappingManagedRootError,
    SystemDirectoryManagedRootError,
    UserProfileManagedRootError,
)
from file_agent.application.history import BatchHistoryEntry, UnavailableBatchHistoryRow
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootUnavailable,
)
from file_agent.application.organization_plan import OrganizationPlanItem, PlanStatus
from file_agent.presentation.messages import Severity, SuggestedAction, UserMessage

# --- Status vocabulary -------------------------------------------------------

_PLAN_STATUS_LABEL: dict[PlanStatus, str] = {
    PlanStatus.READY: "Listo para organizar",
    PlanStatus.REVIEW_REQUIRED: "Necesita tu aprobación",
    PlanStatus.CONFLICT: "No se puede mover todavía",
    PlanStatus.INVALID: "No pudimos confirmar su estado",
    PlanStatus.BLOCKED: "No se moverá por seguridad",
    PlanStatus.SKIPPED: "Omitido",
    PlanStatus.NO_ACTION: "No necesita cambios",
}

_BATCH_ITEM_STATUS_LABEL: dict[BatchApplyItemStatus, str] = {
    BatchApplyItemStatus.APPLIED: "Organizado",
    BatchApplyItemStatus.NOT_APPLIED: "No se movió",
    BatchApplyItemStatus.SKIPPED: "Omitido",
    BatchApplyItemStatus.INVALID: "No se pudo confirmar",
}


def plan_status_label(status: PlanStatus) -> str:
    return _PLAN_STATUS_LABEL[status]


def batch_item_status_label(status: BatchApplyItemStatus) -> str:
    return _BATCH_ITEM_STATUS_LABEL[status]


# --- Reason/rejection vocabulary ---------------------------------------------

# Keyed by raw string value -- works uniformly across PlanReasonCode.value,
# RejectionCode.value, and ApplicationRejectionReason.value, since all three
# are plain `str, Enum` vocabularies. Internal-consistency-only codes
# (basename_mismatch, source_equals_destination, destination_category_
# mismatch, destination_category_path_mismatch, authorization_linkage_
# mismatch) are deliberately absent -- they are not normally user-reachable
# and fall back to the generic message below.
_REASON_DETAIL: dict[str, str] = {
    "destination_occupied": (
        "Ya existe un archivo con ese nombre en la carpeta de destino."
    ),
    "destination_already_exists": (
        "Ya existe un archivo con ese nombre en la carpeta de destino."
    ),
    "review_required": "Necesitamos tu aprobación antes de mover este archivo.",
    "policy_review_without_approval": (
        "Necesitamos tu aprobación antes de mover este archivo."
    ),
    "no_destination_proposed": "No estamos seguros de dónde debería ir este archivo.",
    "source_already_at_destination": "Este archivo ya está organizado.",
    "filesystem_state_uncertain": "No pudimos comprobar esta ubicación de forma segura.",
    "destination_observation_failed": (
        "No pudimos comprobar esta ubicación de forma segura."
    ),
    "policy_block": "FileAgent decidió no mover este archivo por seguridad.",
    "ambiguous_review_history": (
        "No pudimos confirmar el estado de este archivo. No se hizo ningún cambio."
    ),
    "malformed_event_payload": (
        "No pudimos confirmar el estado de este archivo. No se hizo ningún cambio."
    ),
    "human_skipped": "Se omitió este archivo a tu pedido.",
    "review_outcome_is_skip": "Se omitió este archivo a tu pedido.",
    "destination_parent_missing": "La carpeta de destino no existe todavía.",
    "destination_unsafe": "No pudimos confirmar que la carpeta de destino sea segura.",
    "destination_outside_sandbox": (
        "No pudimos confirmar que la carpeta de destino sea segura."
    ),
    "destination_unsafe_reparse_point": (
        "No pudimos confirmar que la carpeta de destino sea segura."
    ),
    "source_not_found": "Ya no encontramos este archivo en su ubicación original.",
    "source_identity_changed": (
        "El archivo cambió desde la última revisión. Vuelve a analizarlo antes de moverlo."
    ),
    "source_hash_mismatch": (
        "El archivo cambió desde la última revisión. Vuelve a analizarlo antes de moverlo."
    ),
    "policy_decision_not_found": (
        "No pudimos encontrar información suficiente sobre este archivo. "
        "Vuelve a analizarlo."
    ),
    "proposal_not_found": (
        "No pudimos encontrar información suficiente sobre este archivo. "
        "Vuelve a analizarlo."
    ),
    "discovered_file_not_found": (
        "No pudimos encontrar información suficiente sobre este archivo. "
        "Vuelve a analizarlo."
    ),
    "managed_root_not_active": (
        "FileAgent ya no administra esta carpeta. Agrégala de nuevo y "
        "vuelve a analizarla si quieres organizarla."
    ),
}

_FALLBACK_DETAIL = (
    "No pudimos completar esta acción de forma segura. "
    "No se realizó ningún cambio en este archivo."
)

# reason_codes that mean "the file itself changed since it was last
# analyzed" -- the one case that gets a REANALYZE suggested_action rather
# than NONE.
_SOURCE_CHANGED_CODES = frozenset(
    {"source_identity_changed", "source_hash_mismatch", "source_not_found"}
)


def rejection_reason_detail(reason_code: str | None) -> str:
    if reason_code is None:
        return _FALLBACK_DETAIL
    return _REASON_DETAIL.get(reason_code, _FALLBACK_DETAIL)


# --- Plan item messages -------------------------------------------------------

_PLAN_STATUS_SEVERITY: dict[PlanStatus, Severity] = {
    PlanStatus.READY: Severity.INFO,
    PlanStatus.REVIEW_REQUIRED: Severity.ATTENTION,
    PlanStatus.CONFLICT: Severity.ATTENTION,
    PlanStatus.INVALID: Severity.ERROR,
    PlanStatus.BLOCKED: Severity.ERROR,
    PlanStatus.SKIPPED: Severity.INFO,
    PlanStatus.NO_ACTION: Severity.INFO,
}

_PLAN_STATUS_ACTION: dict[PlanStatus, SuggestedAction] = {
    PlanStatus.READY: SuggestedAction.NONE,
    PlanStatus.REVIEW_REQUIRED: SuggestedAction.APPROVE,
    PlanStatus.CONFLICT: SuggestedAction.REVIEW_CONFLICT,
    PlanStatus.INVALID: SuggestedAction.NONE,
    PlanStatus.BLOCKED: SuggestedAction.NONE,
    PlanStatus.SKIPPED: SuggestedAction.NONE,
    PlanStatus.NO_ACTION: SuggestedAction.NONE,
}

_PLAN_READY_DETAIL = "Este archivo está listo para organizarse."


def plan_item_message(item: OrganizationPlanItem) -> UserMessage:
    severity = _PLAN_STATUS_SEVERITY[item.status]
    suggested_action = _PLAN_STATUS_ACTION[item.status]
    if item.reason_code in _SOURCE_CHANGED_CODES:
        severity = Severity.ERROR
        suggested_action = SuggestedAction.REANALYZE
    detail = (
        rejection_reason_detail(item.reason_code)
        if item.reason_code is not None
        else _PLAN_READY_DETAIL
    )
    return UserMessage(
        title=plan_status_label(item.status),
        detail=detail,
        severity=severity,
        suggested_action=suggested_action,
    )


# --- Batch item / summary messages -------------------------------------------

_BATCH_ITEM_STATUS_SEVERITY: dict[BatchApplyItemStatus, Severity] = {
    BatchApplyItemStatus.APPLIED: Severity.INFO,
    BatchApplyItemStatus.NOT_APPLIED: Severity.ATTENTION,
    BatchApplyItemStatus.SKIPPED: Severity.INFO,
    BatchApplyItemStatus.INVALID: Severity.ERROR,
}

_BATCH_ITEM_APPLIED_DETAIL = "Este archivo se organizó correctamente."


def batch_item_message(item: BatchApplyItemResult) -> UserMessage:
    severity = _BATCH_ITEM_STATUS_SEVERITY[item.status]
    suggested_action = SuggestedAction.NONE
    if (
        item.status is BatchApplyItemStatus.NOT_APPLIED
        and item.reason_code in _SOURCE_CHANGED_CODES
    ):
        severity = Severity.ERROR
        suggested_action = SuggestedAction.REANALYZE
    detail = (
        rejection_reason_detail(item.reason_code)
        if item.reason_code is not None
        else _BATCH_ITEM_APPLIED_DETAIL
    )
    return UserMessage(
        title=batch_item_status_label(item.status),
        detail=detail,
        severity=severity,
        suggested_action=suggested_action,
    )


_INCOMPLETE_BATCH_MESSAGE = UserMessage(
    title="Esta operación no terminó por completo.",
    detail="Algunos archivos sí pudieron organizarse antes de la interrupción.",
    severity=Severity.ATTENTION,
    suggested_action=SuggestedAction.NONE,
)


def _summary_message(*, selected: int, applied: int, not_applied: int) -> UserMessage:
    if selected == 0:
        # apply_items rejects an empty selection before any result exists --
        # defensive only, never reachable via the public API.
        return UserMessage(
            title="No se realizó ningún cambio.",
            detail="No se seleccionó ningún archivo.",
            severity=Severity.INFO,
            suggested_action=SuggestedAction.NONE,
        )
    if applied == selected:
        return UserMessage(
            title=f"{applied} archivos se organizaron correctamente.",
            detail="Todos los archivos seleccionados se movieron a su carpeta.",
            severity=Severity.INFO,
            suggested_action=SuggestedAction.NONE,
        )
    if applied == 0:
        return UserMessage(
            title="No se realizó ningún cambio.",
            detail="Ninguno de los archivos seleccionados se pudo mover.",
            severity=Severity.ATTENTION,
            suggested_action=SuggestedAction.NONE,
        )
    return UserMessage(
        title=f"{applied} archivos se organizaron. {not_applied} no se pudieron mover.",
        detail="Revisa los archivos que no se movieron para ver más detalles.",
        severity=Severity.ATTENTION,
        suggested_action=SuggestedAction.NONE,
    )


def batch_summary_message(result: BatchApplyResult) -> UserMessage:
    if result.status is BatchStatus.INCOMPLETE:
        return _INCOMPLETE_BATCH_MESSAGE
    return _summary_message(
        selected=result.summary.selected,
        applied=result.summary.applied,
        not_applied=result.summary.not_applied,
    )


def history_summary_message(entry: BatchHistoryEntry) -> UserMessage:
    if entry.status is BatchStatus.INCOMPLETE:
        return _INCOMPLETE_BATCH_MESSAGE
    return _summary_message(
        selected=entry.selected_count,
        applied=entry.applied_count,
        not_applied=entry.not_applied_count,
    )


def unavailable_history_row_message(row: UnavailableBatchHistoryRow) -> UserMessage:
    return UserMessage(
        title="No pudimos mostrar los detalles de esta operación.",
        detail=_FALLBACK_DETAIL,
        severity=Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )


# --- FA-015: Managed Roots -----------------------------------------------------
#
# "Managed Root" is never exposed as primary UI vocabulary -- "Carpetas que
# FileAgent puede organizar" is the only user-facing framing. None of these
# messages ever influence authorization; they render an already-final
# decision (a raised ManagedRootRegistrationError, or an already-computed
# ManagedRootUnavailable/rejection outcome), strictly after the fact.

_MANAGED_ROOT_UNAVAILABLE_NOW_DETAIL = "No encontramos esta carpeta en este momento."

_REGISTRATION_OVERLAP_CHILD_DETAIL = (
    "Esta carpeta está dentro de otra carpeta que FileAgent ya organiza."
)
_REGISTRATION_OVERLAP_PARENT_DETAIL = (
    "Esta carpeta contiene otra carpeta que FileAgent ya organiza."
)
_REGISTRATION_BROAD_ROOT_DETAIL = (
    "Esta carpeta es demasiado grande para organizar directamente. Elige "
    "una carpeta más específica, como Descargas o Documentos."
)

_UNDO_HISTORICAL_ROOT_UNAVAILABLE_DETAIL = (
    "No pudimos deshacer este cambio porque ya no encontramos la carpeta original."
)
_RESTORE_HISTORICAL_ROOT_UNAVAILABLE_DETAIL = (
    "No pudimos restaurar este archivo porque ya no encontramos la carpeta original."
)


def managed_root_registration_error_message(
    exc: ManagedRootRegistrationError,
) -> UserMessage:
    """Total over every ManagedRootRegistrationError subtype: an unmapped
    future subtype (or the bare base class) renders the safe generic
    fallback, exactly like rejection_reason_detail does for unmapped
    reason_codes -- never raises, never shows an empty/English string."""
    if isinstance(exc, DuplicateManagedRootError):
        detail = "Esta carpeta ya está agregada."
    elif isinstance(exc, OverlappingManagedRootError):
        # Directional: is the PROPOSED path nested inside the existing
        # root, or does it contain the existing root? Determined at render
        # time from the two paths the exception already carries -- never
        # re-derived from anything else.
        if exc.path.is_relative_to(exc.existing_path):
            detail = _REGISTRATION_OVERLAP_CHILD_DETAIL
        else:
            detail = _REGISTRATION_OVERLAP_PARENT_DETAIL
    elif isinstance(exc, FilesystemRootManagedRootError):
        detail = "No puedes agregar una unidad completa. Elige una carpeta específica."
    elif isinstance(
        exc, (UserProfileManagedRootError, SystemDirectoryManagedRootError)
    ):
        detail = _REGISTRATION_BROAD_ROOT_DETAIL
    elif isinstance(exc, AppDataManagedRootError):
        detail = (
            "Esta carpeta es utilizada internamente por FileAgent y no se "
            "puede organizar."
        )
    elif isinstance(exc, (InvalidManagedRootPathError, ManagedRootReparsePointError)):
        detail = "No pudimos comprobar esta carpeta de forma segura."
    else:
        detail = _FALLBACK_DETAIL
    return UserMessage(
        title="No se pudo agregar esta carpeta.",
        detail=detail,
        severity=Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )


def managed_root_unavailable_message(
    unavailable: ManagedRootUnavailable,
) -> UserMessage:
    """Renders analyze_managed_root/create_organization_plan/apply_items'
    ManagedRootUnavailable outcome -- NOT_FOUND (never registered, or
    removed) and UNAVAILABLE (registered but currently unresolvable) get
    deliberately distinct copy, matching the distinct user actions each
    implies (re-register vs. wait/check the folder)."""
    if unavailable.status is ManagedRootLookupStatus.NOT_FOUND:
        detail = _REASON_DETAIL["managed_root_not_active"]
    else:
        detail = _MANAGED_ROOT_UNAVAILABLE_NOW_DETAIL
    return UserMessage(
        title="No pudimos organizar esta carpeta.",
        detail=detail,
        severity=Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )


def undo_historical_root_unavailable_message() -> UserMessage:
    """HISTORICAL_ROOT_UNAVAILABLE, undo_transaction specifically -- must
    not share copy with restore_capture's below: they are different user
    actions on different objects (a file move vs. a Vault-recovered file),
    and "deshacer" (undo) copy would be actively wrong shown for a failed
    restore, which was never an undo in the first place."""
    return UserMessage(
        title="No pudimos deshacer este cambio.",
        detail=_UNDO_HISTORICAL_ROOT_UNAVAILABLE_DETAIL,
        severity=Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )


def restore_historical_root_unavailable_message() -> UserMessage:
    """HISTORICAL_ROOT_UNAVAILABLE, restore_capture specifically -- see
    undo_historical_root_unavailable_message's docstring for why this is a
    deliberately separate function/message, not a shared one."""
    return UserMessage(
        title="No pudimos restaurar este archivo.",
        detail=_RESTORE_HISTORICAL_ROOT_UNAVAILABLE_DETAIL,
        severity=Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )
