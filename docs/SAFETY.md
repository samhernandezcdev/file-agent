1. The system never automatically deletes files.

2. During Milestone 0, you cannot move or rename files.

3. The system can only read within the sandbox/ directory.

4. All future modifications to the filesystem must go through a TransactionEngine.

5. No LLM will have direct access to destructive operations.

6. confidence != permission.

7. All future actions must be auditable and reversible.

## Application-owned state

File Agent may write application-owned state only inside its explicitly
configured application data directory.

Application-owned state includes:

- SQLite databases
- migration metadata
- future internal indexes or manifests

Managed user files remain read-only until filesystem mutation is explicitly
introduced through the TransactionEngine milestone.

Persistence code must never use a managed-file path as an application-state path.