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

## Filesystem Structure Safety

1. FileAgent must assume that directory structure may carry semantic or
   functional meaning.

2. A file being correctly classified does not imply that relocating it is safe.

3. FileAgent must not reorganize descendants of detected project,
   application, workspace, package, environment, or other protected trees
   unless an explicit future workflow authorizes management of that tree.

4. Known dependency/build/environment directories should be skipped rather
   than individually classified for organization.

5. User-defined protected roots always override organization proposals.

6. System-managed filesystem locations must be treated as protected by
   default.

7. Protected-tree detection must fail closed:
   uncertainty about whether a structured tree is safe to reorganize should
   result in SKIP/REVIEW, never AUTO.

8. Protection/context evaluation occurs before relocation authorization.

9. AI/LLM confidence cannot override filesystem-structure protection.

10. FileAgent must preserve the invariant:
    understanding a file does not grant permission to relocate it.