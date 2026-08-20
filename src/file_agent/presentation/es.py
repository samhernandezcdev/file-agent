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

from collections.abc import Sequence
from pathlib import Path

from file_agent.application.destination_setup import (
    DestinationPreparationOutcome,
    DestinationPreparationStatus,
    DestinationSetupReasonCode,
)
from file_agent.application.dto import (
    ApplicationRejectionReason,
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
from file_agent.application.history import (
    BatchHistoryEntry,
    BatchHistoryItem,
    UnavailableBatchHistoryRow,
)
from file_agent.application.managed_roots import (
    ManagedRootLookupStatus,
    ManagedRootUnavailable,
)
from file_agent.application.organization_plan import OrganizationPlanItem, PlanStatus
from file_agent.domain import RejectionCode
from file_agent.presentation.messages import Severity, SuggestedAction, UserMessage
from file_agent.structural_safety import StructuralProtection

# --- Status vocabulary -------------------------------------------------------

_PLAN_STATUS_LABEL: dict[PlanStatus, str] = {
    PlanStatus.READY: "Listo para organizar",
    PlanStatus.REVIEW_REQUIRED: "Necesita tu revisión",
    PlanStatus.CONFLICT: "No se puede mover todavía",
    PlanStatus.INVALID: "No pudimos confirmar su estado",
    PlanStatus.BLOCKED: "No se moverá por seguridad",
    PlanStatus.SKIPPED: "Omitido",
    PlanStatus.NO_ACTION: "No necesita cambios",
    PlanStatus.PROTECTED: "Carpeta protegida",
}

_BATCH_ITEM_STATUS_LABEL: dict[BatchApplyItemStatus, str] = {
    BatchApplyItemStatus.APPLIED: "Organizado",
    BatchApplyItemStatus.NOT_APPLIED: "No se organizó",
    BatchApplyItemStatus.SKIPPED: "No se organizó",
    BatchApplyItemStatus.INVALID: "No se pudo confirmar",
}

# FA-017.3: a NOT_APPLIED item whose reason is "the file is already at its
# destination" earns a distinct, more accurate title than the generic
# "No se organizó" -- nothing went wrong, nothing was needed.
_ALREADY_AT_DESTINATION_TITLE = "No fue necesario moverlo"


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
    "source_equals_destination": "El archivo ya estaba en su destino.",
    "filesystem_state_uncertain": "No pudimos comprobar esta ubicación de forma segura.",
    "destination_observation_failed": (
        "No pudimos comprobar esta ubicación de forma segura."
    ),
    "policy_block": "FileAgent decidió no mover este archivo por seguridad.",
    "ambiguous_review_history": "No pudimos confirmar el estado de este archivo.",
    "malformed_event_payload": "No pudimos confirmar el estado de este archivo.",
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
    "structurally_protected": "Esta carpeta está protegida y no se organizará.",
}

# FA-017.3: deliberately does NOT claim "no change was made" -- unlike
# Round 1's version of this constant, this fallback is also reached by a
# FAILED apply's free-text failure_reason (never a _REASON_DETAIL key), for
# which "no change" is not a guaranteed fact (see
# _reason_code_guarantees_source_unchanged below). The unchanged/
# unconfirmed claim is always composed separately, by the caller, never
# baked into this shared reason-explanation text.
_FALLBACK_DETAIL = "No pudimos completar esta acción de forma segura."

# reason_codes that mean "the file itself changed since it was last
# analyzed" -- the one case that gets a REANALYZE suggested_action rather
# than NONE.
_SOURCE_CHANGED_CODES = frozenset(
    {"source_identity_changed", "source_hash_mismatch", "source_not_found"}
)

# FA-017.3: the closed set of reason_code values that can ONLY ever be
# produced strictly before any TransactionEngine mutation -- RejectionCode
# is exclusively prepare()'s own vocabulary (commit() never produces one;
# its only failure mode is a free-text failure_reason), and
# ApplicationRejectionReason covers only the pre-engine lookup/policy/
# review checks in _apply_one. A reason_code in this set is architectural
# proof (not a per-instance observation) that the source was never
# touched.
_PRE_COMMIT_REASON_CODES: frozenset[str] = frozenset(
    {member.value for member in RejectionCode}
    | {member.value for member in ApplicationRejectionReason}
)

_UNCHANGED_SENTENCE = "Tu archivo original no se modificó."
_UNCONFIRMED_SENTENCE = "No pudimos confirmar el estado final del archivo."


def _reason_code_guarantees_source_unchanged(reason_code: str | None) -> bool:
    """True only when reason_code is a member of the closed pre-commit
    vocabularies (see _PRE_COMMIT_REASON_CODES). A free-text OS
    failure_reason (the FAILED case) or any future/unrecognized code is
    never a member, and correctly returns False -- "not durably
    provable," never "FileAgent changed it." Never touches the
    filesystem; a pure function of already-known/persisted data."""
    return reason_code is not None and reason_code in _PRE_COMMIT_REASON_CODES


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
    PlanStatus.PROTECTED: Severity.INFO,
}

_PLAN_STATUS_ACTION: dict[PlanStatus, SuggestedAction] = {
    PlanStatus.READY: SuggestedAction.NONE,
    PlanStatus.REVIEW_REQUIRED: SuggestedAction.APPROVE,
    PlanStatus.CONFLICT: SuggestedAction.REVIEW_CONFLICT,
    PlanStatus.INVALID: SuggestedAction.NONE,
    PlanStatus.BLOCKED: SuggestedAction.NONE,
    PlanStatus.SKIPPED: SuggestedAction.NONE,
    PlanStatus.NO_ACTION: SuggestedAction.NONE,
    PlanStatus.PROTECTED: SuggestedAction.NONE,
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

_BATCH_ITEM_APPLIED_DETAIL_FALLBACK = "Este archivo se organizó correctamente."
"""Used only in the defensive/should-not-happen case where an APPLIED
result somehow carries no destination_path."""


_FAILED_MOVE_DETAIL = "No pudimos completar el movimiento."


def _applied_result_detail(destination_path: Path | None) -> str:
    if destination_path is None:
        return _BATCH_ITEM_APPLIED_DETAIL_FALLBACK
    return f"Se movió a {destination_path}."


def _applied_history_detail(
    source_path: Path | None, destination_path: Path | None
) -> str:
    if source_path is None or destination_path is None:
        return _BATCH_ITEM_APPLIED_DETAIL_FALLBACK
    return f"Se movió de {source_path} a {destination_path}."


def _batch_item_title_and_severity(
    status: BatchApplyItemStatus, reason_code: str | None
) -> tuple[str, Severity, SuggestedAction]:
    """Shared by both composers below (FA-017.3 Major 3: shared LOWER-LEVEL
    wording is fine; only the unchanged/unconfirmed sentence -- which needs
    facts each composer has access to differently -- is not shared)."""
    severity = _BATCH_ITEM_STATUS_SEVERITY[status]
    suggested_action = SuggestedAction.NONE
    title = batch_item_status_label(status)
    if (
        status is BatchApplyItemStatus.NOT_APPLIED
        and reason_code == RejectionCode.SOURCE_EQUALS_DESTINATION.value
    ):
        title = _ALREADY_AT_DESTINATION_TITLE
    if reason_code in _SOURCE_CHANGED_CODES:
        severity = Severity.ERROR
        suggested_action = SuggestedAction.REANALYZE
    return title, severity, suggested_action


def batch_item_result_message(
    item: BatchApplyItemResult, *, source_unchanged_confirmed: bool
) -> UserMessage:
    """FA-017.3 execution-time composer (Major 3) -- may consume the
    ephemeral source_unchanged_confirmed fact this apply call itself just
    observed (never persisted; see history_item_message below, which
    structurally cannot receive it)."""
    if item.status is BatchApplyItemStatus.APPLIED:
        return UserMessage(
            title=batch_item_status_label(item.status),
            detail=_applied_result_detail(item.destination_path),
            severity=_BATCH_ITEM_STATUS_SEVERITY[item.status],
            suggested_action=SuggestedAction.NONE,
        )
    title, severity, suggested_action = _batch_item_title_and_severity(
        item.status, item.reason_code
    )
    # item.reason_code is None only for FAILED (never APPLIED, handled
    # above) -- every other non-APPLIED status always carries a real code.
    base_detail = (
        _FAILED_MOVE_DETAIL
        if item.reason_code is None
        else rejection_reason_detail(item.reason_code)
    )
    unchanged_sentence = (
        _UNCHANGED_SENTENCE if source_unchanged_confirmed else _UNCONFIRMED_SENTENCE
    )
    return UserMessage(
        title=title,
        detail=f"{base_detail} {unchanged_sentence}",
        severity=severity,
        suggested_action=suggested_action,
    )


def history_item_message(item: BatchHistoryItem) -> UserMessage:
    """FA-017.3 durable-history composer (Major 3) -- consumes ONLY the
    durably-reconstructed BatchHistoryItem; has no parameter through which
    an ephemeral execution-time fact could arrive (EXECUTION MESSAGE !=
    HISTORY MESSAGE, structurally, not by convention). Where History
    reaches the same "source unchanged" conclusion Result did, it does so
    by independently re-deriving from a static code guarantee
    (_reason_code_guarantees_source_unchanged), never by consuming
    anything Result computed and discarded. Never touches the filesystem."""
    if item.status is BatchApplyItemStatus.APPLIED:
        return UserMessage(
            title=batch_item_status_label(item.status),
            detail=_applied_history_detail(item.source_path, item.destination_path),
            severity=_BATCH_ITEM_STATUS_SEVERITY[item.status],
            suggested_action=SuggestedAction.NONE,
        )
    title, severity, suggested_action = _batch_item_title_and_severity(
        item.status, item.reason_code
    )
    base_detail = rejection_reason_detail(item.reason_code)
    if _reason_code_guarantees_source_unchanged(item.reason_code):
        detail = f"{base_detail} {_UNCHANGED_SENTENCE}"
    else:
        # Durable evidence doesn't prove the unchanged claim either way
        # (a free-text failure_reason, or an unrecognized/future code) --
        # History deliberately says less than Result may have (§Major 3):
        # it never restates an execution-time-only observation it cannot
        # itself prove.
        detail = base_detail
    return UserMessage(
        title=title, detail=detail, severity=severity, suggested_action=suggested_action
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


# --- FA-016: Protected Trees & Exclusions ---------------------------------
#
# "Protected Tree"/"structural protection"/"marker"/"hard exclusion" are
# never exposed as user-facing vocabulary -- "esta carpeta parece formar
# parte de un proyecto" / "carpeta protegida" is the only framing. These
# messages render an already-final, read-only decision (a scan's
# AnalyzedScanResult.protected_trees, or an already-computed
# PlanStatus.PROTECTED/STRUCTURALLY_PROTECTED outcome); they never
# influence which files are eligible for organization.

_PROTECTED_TREE_FOUND_DETAIL = (
    "FileAgent dejó esta carpeta intacta porque parece formar parte de un proyecto."
)
_STRUCTURAL_PROTECTION_NOTE = (
    "Algunos archivos no se organizaron para evitar modificar la "
    "estructura de un proyecto."
)


def protected_trees_summary_message(
    protected_trees: Sequence[StructuralProtection],
) -> UserMessage | None:
    """Renders AnalyzedScanResult.protected_trees -- one message for the
    WHOLE scan (never one per excluded file, matching the aggregate-not-
    per-file design), or None if the scan found nothing to protect. A
    single, deliberately un-itemized message even when multiple project
    folders were found -- naming/counting them individually would start
    exposing internal structural detail this layer is meant to abstract
    away."""
    if not protected_trees:
        return None
    return UserMessage(
        title="Se encontró un proyecto.",
        detail=_PROTECTED_TREE_FOUND_DETAIL,
        severity=Severity.INFO,
        suggested_action=SuggestedAction.NONE,
    )


def missing_destination_folder_message(
    category_label: str, folder_name: str, affected_count: int
) -> UserMessage:
    """FA-017.1 §18: the aggregate, Python-composed copy for a
    PlanAttentionView(variant="missing_destination_folder") entry -- one
    message per distinct missing destination_path.parent, never per file."""
    file_word = "archivo" if affected_count == 1 else "archivos"
    detail = (
        f"{affected_count} {file_word} están listos para clasificarse como "
        f"{category_label}, pero falta:\n\n{folder_name}\n\n"
        "Créala y vuelve a analizar esta carpeta."
    )
    return UserMessage(
        title="Falta preparar esta carpeta",
        detail=detail,
        severity=Severity.ATTENTION,
        suggested_action=SuggestedAction.REANALYZE,
    )


_DESTINATION_SETUP_REASON_DETAIL: dict[DestinationSetupReasonCode, str] = {
    DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED: (
        "Esta carpeta ya no hace falta según el estado actual de la carpeta administrada."
    ),
    DestinationSetupReasonCode.FILE_AT_DESTINATION: "Ya existe un archivo con ese nombre.",
    DestinationSetupReasonCode.UNSAFE_REPARSE_POINT: (
        "No pudimos confirmar que esta ubicación sea segura."
    ),
    DestinationSetupReasonCode.STRUCTURALLY_PROTECTED: (
        "No pudimos confirmar que esta ubicación sea segura."
    ),
    DestinationSetupReasonCode.OBSERVATION_FAILED: _FALLBACK_DETAIL,
}


def destination_preparation_item_message(
    outcome: DestinationPreparationOutcome,
) -> UserMessage:
    """FA-017.2: per-category result copy. PREPARED and ALREADY_AVAILABLE
    are deliberately distinct titles -- provenance matters (existence !=
    provenance, §16 of the design): a folder this call merely found
    already present is never described as something FileAgent just did."""
    if outcome.status is DestinationPreparationStatus.PREPARED:
        return UserMessage(
            title="Preparada",
            detail="FileAgent creó esta carpeta.",
            severity=Severity.INFO,
            suggested_action=SuggestedAction.NONE,
        )
    if outcome.status is DestinationPreparationStatus.ALREADY_AVAILABLE:
        return UserMessage(
            title="Ya estaba disponible",
            detail="Esta carpeta ya existía.",
            severity=Severity.INFO,
            suggested_action=SuggestedAction.NONE,
        )
    assert outcome.reason_code is not None, (
        "NOT_PREPARED always carries a reason_code -- see "
        "DestinationPreparationOutcome's own field docstring"
    )
    detail = _DESTINATION_SETUP_REASON_DETAIL.get(outcome.reason_code, _FALLBACK_DETAIL)
    return UserMessage(
        title="No se pudo preparar",
        detail=detail,
        severity=Severity.INFO
        if outcome.reason_code is DestinationSetupReasonCode.NOT_CURRENTLY_REQUIRED
        else Severity.ERROR,
        suggested_action=SuggestedAction.NONE,
    )


_DESTINATION_SETUP_REANALYZE_NOTE = (
    "FileAgent debe volver a comprobar la carpeta antes de organizar."
)


def destination_setup_summary_message(
    outcomes: Sequence[DestinationPreparationOutcome],
) -> UserMessage:
    """FA-017.2: provenance-aware aggregate copy -- never implies FileAgent
    created every listed folder when some were merely already available
    (Round 2 Final Errata, Minor 1)."""
    total = len(outcomes)
    prepared = sum(
        1 for o in outcomes if o.status is DestinationPreparationStatus.PREPARED
    )
    already_available = sum(
        1
        for o in outcomes
        if o.status is DestinationPreparationStatus.ALREADY_AVAILABLE
    )
    ready = prepared + already_available
    not_prepared = total - ready

    if not_prepared > 0:
        title = f"{ready} de {total} carpetas están listas."
        severity = Severity.ATTENTION
    elif already_available == 0:
        title = f"{prepared} carpetas preparadas."
        severity = Severity.INFO
    elif prepared == 0:
        title = "Estas carpetas ya estaban listas."
        severity = Severity.INFO
    else:
        title = "Los destinos están listos."
        severity = Severity.INFO

    return UserMessage(
        title=title,
        detail=_DESTINATION_SETUP_REANALYZE_NOTE,
        severity=severity,
        suggested_action=SuggestedAction.REANALYZE,
    )


def structural_protection_note(protected_count: int) -> str | None:
    """A plan/batch-level explanatory note for when >=1 item's status is
    PlanStatus.PROTECTED -- callers append this to whatever summary message
    (plan or batch) they are already rendering. None if nothing was
    structurally protected, so callers can skip the note entirely rather
    than rendering an empty addition."""
    if protected_count <= 0:
        return None
    return _STRUCTURAL_PROTECTION_NOTE
