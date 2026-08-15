"""Errors raised by the vault engine itself -- not VaultRejectionCode, which
represents a legitimate precondition outcome on a real capture request."""


class InvalidVaultConfigurationError(ValueError):
    """Raised by VaultEngine.__init__ (never by capture()) when the engine
    cannot be safely constructed:

    - the app-owned root (AppPaths.root, and therefore its vault_root child)
      overlaps the managed/sandbox root (equal, one inside the other), or
    - bootstrap finds the Vault's own directory tree already replaced by a
      symlink/junction.

    Construction fails closed before any Vault I/O is attempted. Never
    raised by capture() itself -- a per-capture discovery that a Vault
    directory has since become an unsafe reparse point is reported as a
    REJECTED VaultCaptureResult (VaultRejectionCode.VAULT_STORAGE_UNSAFE)
    instead, since that is a per-request environmental precondition on an
    already-valid engine, not a setup-time misconfiguration.
    """
