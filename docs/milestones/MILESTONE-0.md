# Milestone 0 — Observe

Status: CLOSED

## Completed tickets

- FA-001 — Domain Model Foundation
- FA-002 — Read-Only Directory Scanner
- FA-003 — Safe Read-Only File Hashing
- FA-004 — Persistent Audit Store
- FA-004.1 — Persistence hardening

## Guarantees

- Managed user files remain read-only.
- Filesystem access is constrained to an explicit sandbox.
- Symlink/junction/reparse-point escapes are detected and blocked.
- File hashing is streamed and identity-checked.
- Untrusted hashes are discarded.
- Scan observations survive process restarts.
- Trusted hash enrichment is persisted atomically with its FILE_HASHED event.
- Audit events are append-only through the public persistence API.
- Same event id + same content is idempotent.
- Same event id + different content is an integrity failure.
- SQLite writes are confined to explicit application-owned storage.
- Alembic owns production schema evolution.

## Current architecture

SandboxRoot
    ↓
DirectoryScanner
    ↓
ScanResult
├── ScanRun
├── DiscoveredFile[]
├── FILE_DISCOVERED events
└── ScanIssue[]

    ↓

FileHasher
    ↓
HashOutcome
├── HashSuccess
│   ├── enriched DiscoveredFile
│   └── FILE_HASHED event
└── HashFailure

    ↓

FileAgentStore
    ↓
SQLite
├── scans
├── file_observations
└── domain_events

## Identity semantics

`DiscoveredFile.id` identifies one discovered-file observation and its
`with_sha256()` enrichment lineage.

It is not a stable identity for a real-world file across separate scans.

SHA-256 identifies content, not filesystem identity.

No cross-scan logical-file reconciliation exists yet.

## Storage semantics

`file_observations.sha256` contains the latest trusted hash known for that
observation.

Historical trusted hash results remain represented by append-only
`FILE_HASHED` events.

## Threat-model limitations

The current filesystem implementation is path-based rather than
Windows-handle-based.

It does not claim protection against an adversarial process exploiting
precisely timed TOCTOU filesystem races.

No exclusive file locking is used during hashing.

UNC roots and several advanced Windows filesystem cases remain deferred.

## Deferred work

- classification
- proposal generation
- confidence/policy engine
- managed-file TransactionEngine
- quarantine
- backup vault
- undo/restore
- watcher
- UI
- runtime LLM integration