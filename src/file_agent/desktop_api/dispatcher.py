"""Command dispatch: closed-set lookup, per-command param parsing, handler
invocation, and mapping of every FileAgentApplicationService "invalid
caller input" exception (never a business-state outcome -- see
application/errors.py) to a normal, fully-completed `ok: false,
kind: "product_rejection"` terminal frame.

A genuinely unexpected exception (a real bug) is deliberately NOT caught
here -- it propagates to __main__.py's worker loop, which renders it as a
per-request `kind: "fatal"` terminal frame (the sidecar PROCESS survives;
only this one request failed) and logs the real traceback to stderr. Only
a confirmed protocol WRITE failure ever triggers the process-wide
os._exit() fatal-transport primitive in protocol.py -- a handler bug never
does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from file_agent.application import FileAgentApplicationService
from file_agent.application.errors import (
    DuplicatePolicyDecisionIdError,
    EmptyBatchSelectionError,
    ManagedRootRegistrationError,
    MixedManagedRootsError,
)
from file_agent.desktop_api import views as v
from file_agent.desktop_api.errors import UnknownCommandError
from file_agent.desktop_api.handlers import HANDLERS

_GENERIC_INPUT_REJECTION_DETAIL = (
    "No pudimos completar esta acción de forma segura. "
    "No se realizó ningún cambio en este archivo."
)


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    ok: bool
    result: dict[str, Any] | None = None
    error_kind: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def dispatch(
    command: str, raw_params: dict[str, Any], service: FileAgentApplicationService
) -> DispatchOutcome:
    entry = HANDLERS.get(command)
    if entry is None:
        raise UnknownCommandError(command)

    try:
        params = entry.params_model.model_validate(raw_params)
    except ValidationError as exc:
        return DispatchOutcome(
            ok=False,
            error_kind="invalid_params",
            error_code="invalid_params",
            error_message=str(exc),
        )

    try:
        view = entry.handler(service, params)
    except ManagedRootRegistrationError as exc:
        message = v.managed_root_registration_error_view(exc)
        return DispatchOutcome(
            ok=False,
            error_kind="product_rejection",
            error_code=type(exc).__name__,
            error_message=message.detail,
        )
    except (
        DuplicatePolicyDecisionIdError,
        EmptyBatchSelectionError,
        MixedManagedRootsError,
    ) as exc:
        return DispatchOutcome(
            ok=False,
            error_kind="product_rejection",
            error_code=type(exc).__name__,
            error_message=_GENERIC_INPUT_REJECTION_DETAIL,
        )

    return DispatchOutcome(ok=True, result=view.model_dump(mode="json", by_alias=True))
