"""Adversarial tests for the prepared-capability bypass surface (round 2/3).

Imports _PreparedMove via the private module path -- the same way any other
leading-underscore internal in this codebase is reachable by code that
specifically needs to (not advertised via __init__.py).
"""

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from file_agent.domain import (
    ExecutionAuthorization,
    PolicyDecision,
    TransactionRequest,
    TransactionResult,
    TransactionStatus,
)
from file_agent.scanner import SandboxRoot
from file_agent.transaction_engine import TransactionEngine
from file_agent.transaction_engine.engine import _PreparedMove
from file_agent.transaction_engine.errors import InvalidPreparedMoveError


def test_forged_prepared_move_cannot_commit(sandbox_root: SandboxRoot) -> None:
    engine = TransactionEngine(sandbox_root)
    forged = _PreparedMove(_token=uuid4())

    with pytest.raises(InvalidPreparedMoveError):
        engine.commit(forged)


def test_prepared_move_from_another_engine_instance_cannot_commit(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine_a = TransactionEngine(sandbox_root)
    engine_b = TransactionEngine(sandbox_root)
    prepared = engine_a.prepare(request, authorization)
    assert not isinstance(prepared, TransactionResult)

    with pytest.raises(InvalidPreparedMoveError):
        engine_b.commit(prepared)

    # the source is untouched -- engine_a's own registry still holds the
    # capability, but nothing forced a commit through the wrong instance
    assert source.exists()


def test_same_prepared_move_cannot_commit_twice(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    prepared = engine.prepare(request, authorization)
    assert not isinstance(prepared, TransactionResult)

    first = engine.commit(prepared)
    assert first.status is TransactionStatus.SUCCEEDED

    with pytest.raises(InvalidPreparedMoveError):
        engine.commit(prepared)


def test_rejected_prepare_never_produces_a_committable_capability(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    source = make_source_file("report.txt")
    request = make_request(source)
    # A policy decision for a DIFFERENT policy_decision_id can never
    # legitimately authorize this request -- forces a REJECTED outcome
    # deterministically, without depending on TransactionEngine inspecting
    # PolicyDecision.decision itself (it no longer does).
    policy_decision = make_policy_decision(request, id=uuid4())
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    outcome = engine.prepare(request, authorization)

    assert isinstance(outcome, TransactionResult)
    assert not isinstance(outcome, _PreparedMove)
    # there is no legitimate value of type _PreparedMove to extract from a
    # REJECTED TransactionResult -- the only way to reach commit() is via a
    # genuine prepare() success, which this call did not produce


def test_commit_ignores_caller_controlled_state_and_uses_only_the_registry(
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
    make_request: Callable[..., TransactionRequest],
    make_policy_decision: Callable[..., PolicyDecision],
) -> None:
    """A NEW _PreparedMove instance built from a token COPIED off a genuine,
    still-pending capability still commits successfully using the engine's
    own stored request/hash data -- proving commit() is driven entirely by
    the token-keyed registry lookup, never by the identity of the object
    the caller happens to pass in."""
    source = make_source_file("report.txt", content=b"hello world")
    request = make_request(source, content=b"hello world")
    policy_decision = make_policy_decision(request)
    authorization = ExecutionAuthorization.from_policy_auto(policy_decision)

    engine = TransactionEngine(sandbox_root)
    prepared = engine.prepare(request, authorization)
    assert not isinstance(prepared, TransactionResult)

    copied_token_capability = _PreparedMove(_token=prepared._token)
    assert copied_token_capability is not prepared

    result = engine.commit(copied_token_capability)

    assert result.status is TransactionStatus.SUCCEEDED
    assert not source.exists()
    assert request.destination_path.exists()
