"""Transport/protocol-level errors -- distinct from FileAgentApplicationService's
own product exceptions (application/errors.py), which handlers.py catches
and maps to a normal REJECTED-shaped View DTO result, never one of these.

These three are the only conditions that produce a terminal error frame
(`ok: false`) rather than a normal `ok: true` result carrying a
REJECTED/FAILED-status View DTO -- see dispatcher.py.
"""

from __future__ import annotations


class DesktopApiError(Exception):
    """Base for every desktop_api transport/protocol-level error."""


class UnknownCommandError(DesktopApiError):
    """`command` is not one of the 14 closed catalogue entries. No
    generic-invoke, no dynamic import, no fallback dispatch -- an unknown
    command is always rejected before touching FileAgentApplicationService."""

    def __init__(self, command: str) -> None:
        super().__init__(f"unknown command: {command!r}")
        self.command = command


class MalformedRequestError(DesktopApiError):
    """The request line failed to parse as a well-formed request frame
    (invalid JSON, missing/wrong-typed `id`/`command`/`params`). Carries
    `request_id` only when one could genuinely be recovered from the
    otherwise-malformed input -- see __main__.py's reader loop for how the
    two cases (id recoverable vs. not) are handled differently."""

    def __init__(self, message: str, *, request_id: str | None) -> None:
        super().__init__(message)
        self.request_id = request_id
