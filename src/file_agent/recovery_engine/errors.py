"""Errors raised by the recovery engine itself -- not RecoveryRejectionCode,
which represents a legitimate precondition outcome on a real request."""

from file_agent.vault_engine import InvalidVaultConfigurationError


class InvalidRecoveryConfigurationError(InvalidVaultConfigurationError):
    """Raised by RecoveryEngine.__init__ when the engine cannot be safely
    constructed -- the app-owned root overlaps the managed/sandbox root.
    Inherits from InvalidVaultConfigurationError rather than duplicating it:
    it is the same underlying root-overlap problem, checked via the same
    imported vault_engine.safety.ensure_disjoint_roots. Never raised by
    prepare()/commit() -- a per-call discovery of an unsafe Vault directory
    is reported as a REJECTED RecoveryResult instead (see
    RecoveryRejectionCode.VAULT_STORAGE_UNSAFE), not an exception.
    """


class InvalidPreparedRecoveryError(ValueError):
    """Raised by RecoveryEngine.commit() when the given prepared recovery's
    token is not a live entry in this engine instance's own pending-
    preparation registry.

    Covers three distinct cases, deliberately not distinguished further: a
    forged/hand-built prepared recovery, one issued by a DIFFERENT
    RecoveryEngine instance, and one that was already committed once
    (one-shot consumption). Never raised for a genuine, unconsumed prepared
    recovery from THIS engine's own prepare(). Mirrors
    transaction_engine.errors.InvalidPreparedMoveError exactly.
    """
