"""Signature-level proof of the trust boundary: no public
FileAgentApplicationService method accepts CompletedMoveEvidence,
VaultCaptureEvidence, TransactionRequest, ReverseMoveRequest,
RestoreFromVaultRequest, PolicyDecision, HumanReviewDecision,
ExecutionAuthorization, or any _Prepared* capability type as a parameter.
Every mutating method's only parameters are UUIDs (plus an optional str note
for review actions). ExecutionAuthorization in particular must only ever be
constructed internally by FileAgentApplicationService itself, from persisted
facts -- never accepted from a caller."""

import inspect

from file_agent.application import FileAgentApplicationService

FORBIDDEN_ANNOTATION_SUBSTRINGS = (
    "CompletedMoveEvidence",
    "VaultCaptureEvidence",
    "TransactionRequest",
    "ReverseMoveRequest",
    "RestoreFromVaultRequest",
    "PolicyDecision",
    "HumanReviewDecision",
    "ExecutionAuthorization",
    "_Prepared",
    "Prepared",
)

PUBLIC_METHOD_NAMES = (
    "analyze_scan",
    "analyze_file",
    "approve_review",
    "skip_review",
    "apply_item",
    "undo_transaction",
    "restore_capture",
)


def test_public_methods_exist() -> None:
    for name in PUBLIC_METHOD_NAMES:
        assert hasattr(FileAgentApplicationService, name), (
            f"missing public method: {name}"
        )


def test_no_public_method_accepts_a_forbidden_internal_type() -> None:
    offenders: list[str] = []
    for name in PUBLIC_METHOD_NAMES:
        method = getattr(FileAgentApplicationService, name)
        signature = inspect.signature(method)
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            annotation = str(param.annotation)
            for forbidden in FORBIDDEN_ANNOTATION_SUBSTRINGS:
                if forbidden in annotation:
                    offenders.append(f"{name}({param_name}: {annotation})")

    assert not offenders, f"forbidden parameter types found: {offenders}"


def test_mutating_methods_take_only_uuid_and_optional_note() -> None:
    mutating = (
        "approve_review",
        "skip_review",
        "apply_item",
        "undo_transaction",
        "restore_capture",
    )
    for name in mutating:
        method = getattr(FileAgentApplicationService, name)
        signature = inspect.signature(method)
        params = {
            pname: p
            for pname, p in signature.parameters.items()
            if pname not in ("self",)
        }
        for pname, param in params.items():
            annotation = str(param.annotation)
            assert "UUID" in annotation or pname == "note", (
                f"{name}({pname}: {annotation}) is not a UUID or the optional note parameter"
            )
