"""FA-017 Round 7 §"commands.json": the manifest is a contract/drift guard,
never runtime authorization. This proves the Python-side half of that
contract: the dispatcher's registered handler set, the retry-safety
catalogue, and commands.json itself all agree on exactly the same 14
command names and classifications -- no wildcard/default arm, no silent
drift between the three."""

from file_agent.desktop_api.handlers import HANDLERS
from file_agent.desktop_api.protocol import (
    COMMAND_NAMES,
    RETRY_SAFETY_BY_COMMAND,
    RetrySafety,
)

_EXPECTED_SAFE_RETRY = frozenset(
    {
        "managed_roots.list",
        "analysis.run",
        "analysis.reanalyze_file",
        "plan.create",
        "history.get_batch",
        "history.list_recent",
    }
)

_EXPECTED_UNKNOWN_ON_DISCONNECT = frozenset(
    {
        "managed_roots.add",
        "managed_roots.remove",
        "review.approve",
        "review.skip",
        "apply.item",
        "apply.items",
        "recovery.undo_transaction",
        "recovery.restore_capture",
    }
)


def test_exactly_fourteen_commands() -> None:
    assert len(COMMAND_NAMES) == 14
    assert len(HANDLERS) == 14


def test_dispatcher_handler_set_matches_manifest() -> None:
    assert set(HANDLERS.keys()) == COMMAND_NAMES


def test_retry_safety_exhaustive_and_matches_expected_split() -> None:
    assert set(RETRY_SAFETY_BY_COMMAND.keys()) == COMMAND_NAMES
    safe_retry = {
        name
        for name, safety in RETRY_SAFETY_BY_COMMAND.items()
        if safety is RetrySafety.SAFE_RETRY
    }
    unknown_on_disconnect = {
        name
        for name, safety in RETRY_SAFETY_BY_COMMAND.items()
        if safety is RetrySafety.UNKNOWN_ON_DISCONNECT
    }
    assert safe_retry == _EXPECTED_SAFE_RETRY
    assert unknown_on_disconnect == _EXPECTED_UNKNOWN_ON_DISCONNECT
    assert safe_retry | unknown_on_disconnect == COMMAND_NAMES
    assert safe_retry & unknown_on_disconnect == set()


def test_review_approve_and_skip_are_unknown_on_disconnect_despite_no_file_move() -> (
    None
):
    """review.approve/skip never move a managed file, but persist a human
    decision -- UNKNOWN_ON_DISCONNECT, not "mutating vs read-only"."""
    assert (
        RETRY_SAFETY_BY_COMMAND["review.approve"] is RetrySafety.UNKNOWN_ON_DISCONNECT
    )
    assert RETRY_SAFETY_BY_COMMAND["review.skip"] is RetrySafety.UNKNOWN_ON_DISCONNECT


def test_analysis_run_is_safe_retry_despite_writing_audit_state() -> None:
    """Rerunning analysis creates a fresh valid analysis generation and is
    an expected recovery action -- SAFE_RETRY despite recording a scan."""
    assert RETRY_SAFETY_BY_COMMAND["analysis.run"] is RetrySafety.SAFE_RETRY
