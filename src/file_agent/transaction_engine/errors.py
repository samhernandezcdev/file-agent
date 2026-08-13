"""Errors raised by the transaction engine itself -- not RejectionCode, which
represents a legitimate precondition outcome on a real request."""


class InvalidPreparedMoveError(ValueError):
    """Raised by TransactionEngine.commit() when the given prepared move's
    token is not a live entry in this engine instance's own
    pending-preparation registry.

    Covers three distinct cases, deliberately not distinguished further:
    a forged/hand-built prepared move, one issued by a DIFFERENT
    TransactionEngine instance, and one that was already committed once
    (one-shot consumption). Never raised for a genuine, unconsumed prepared
    move from THIS engine's own prepare().
    """
