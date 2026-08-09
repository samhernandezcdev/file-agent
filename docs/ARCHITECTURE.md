# Architecture

## Current system

File Agent currently implements Milestone 0 — Observe.

```text
Managed filesystem
        |
        v
   SandboxRoot
        |
        v
 DirectoryScanner
        |
        v
    ScanResult
   /    |     \
ScanRun Files Events
        |
        v
    FileHasher
        |
        v
   HashOutcome
        |
        v
  FileAgentStore
        |
        v
      SQLite
```

## Core boundaries

### Domain

Pure immutable models and domain vocabulary.

The domain does not perform filesystem or database I/O.

### Scanner

Reads filesystem metadata within an explicitly validated sandbox.

It does not hash file content, classify files, persist data, or mutate managed files.

### Hasher

Reads file content only after containment and identity checks.

A hash is trusted only when the observed file remains consistent with the expected observation.

It does not mutate managed files.

### Persistence

Persists scans, file observations, and domain events in application-owned SQLite storage.

It does not decide what files mean and does not mutate managed files.

## Current identity model

A `DiscoveredFile.id` identifies one observation and its enrichment lineage.

It is not a stable identity for a filesystem object across scans.

Two observations may:

* have the same path;
* have the same SHA-256;
* represent different scan occurrences.

SHA-256 represents content identity, not filesystem identity.

No logical cross-scan file entity exists yet.

## Audit model

`domain_events` is the append-only historical record.

Materialized columns such as `file_observations.sha256` represent current trusted state for that observation.

Historical trusted values remain available through events.

## Mutation boundary

No managed-file mutation exists yet.

Future rename, move, quarantine, restore, or deletion operations must go through a dedicated TransactionEngine.

Classification, LLM output, confidence scores, and policy decisions must never directly invoke filesystem mutation.

## Milestones

### Milestone 0 — Observe

Closed.

Capabilities:

* discover files;
* capture metadata;
* safely hash content;
* persist observations;
* preserve audit history;
* restore persisted state after process restart.

### Milestone 1 — Understand

Next.

Planned capabilities:

* classify observed files;
* generate organization proposals;
* assign confidence;
* apply policy to determine whether a proposal may eventually become actionable.

Milestone 1 remains read-only with respect to managed user files.
