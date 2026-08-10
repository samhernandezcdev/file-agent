# Milestone 1 — Understand

Status: CLOSED

## Completed

* FA-005 — Deterministic File Classification
* FA-005.1 — Classification hardening
* FA-006 — Proposal Engine
* FA-006.1 — Proposal Engine test hardening
* FA-007 — Confidence + Policy
* FA-007.1 — Policy test hardening

## Current capabilities

File Agent can now take an observed file through a deterministic,
explainable understanding pipeline without filesystem mutation:

1. classify the observed file
2. propose a logical organization destination
3. evaluate the proposal against policy
4. persist the resulting classification, proposal, and policy history

The current pipeline is:

`DiscoveredFile -> ClassificationResult -> FileProposal -> PolicyDecision`

### Classification

Current taxonomy:

* DOCUMENT
* IMAGE
* AUDIO
* VIDEO
* ARCHIVE
* CODE
* EXECUTABLE
* OTHER
* UNKNOWN

Classification results include:

* source file observation
* category
* confidence
* reasons
* timestamp
* classifier provenance

Classification history may be persisted as `FILE_CLASSIFIED` events.

### Proposal generation

FA-006 converts a classification into a logical organization proposal.

Current logical destination taxonomy:

* DOCUMENTS
* IMAGES
* AUDIO
* VIDEO
* ARCHIVES
* CODE
* EXECUTABLES

A proposal may include:

* source file id
* source classification category
* logical destination category
* proposal confidence
* source classification confidence
* classifier provenance
* proposal-engine provenance
* explainability reasons

FA-006 does not resolve a logical destination into a filesystem path.

The existing physical `proposed_destination` field remains `None`.

Filename renaming is not supported in this milestone:

`proposed_name = None`

UNKNOWN and OTHER classifications produce valid proposals with no logical
destination rather than inventing a destination.

Proposal history may be persisted as `PROPOSAL_CREATED` events.

### Policy evaluation

FA-007 evaluates a `FileProposal` and produces a deterministic
`PolicyDecision`.

Current policy outcomes:

* AUTO
* REVIEW
* BLOCK

`AUTO` means the proposal is eligible for future automatic execution,
subject to later TransactionEngine and runtime safety checks.

`REVIEW` means the proposal is not eligible for automatic execution and
requires human review before any future managed-file mutation.

`BLOCK` represents an explicit policy prohibition.

`BLOCK` is part of the domain vocabulary but is not produced by
`rules-v1`.

The core policy invariant is:

`confidence != permission`

A high-confidence proposal does not automatically receive AUTO.

For example:

`EXECUTABLE + EXECUTABLES + confidence=1.0 -> REVIEW`

AUTO uses explicit positive eligibility.

The current policy allowlist contains:

* DOCUMENT -> DOCUMENTS
* IMAGE -> IMAGES
* AUDIO -> AUDIO
* VIDEO -> VIDEO
* ARCHIVE -> ARCHIVES
* CODE -> CODE

For an allowlisted category/destination pair, proposal confidence must satisfy:

`AUTO_CONFIDENCE_THRESHOLD = 1.0`

Anything not explicitly eligible for AUTO falls back to REVIEW under
`rules-v1`.

Policy history may be persisted as `POLICY_EVALUATED` events.

## Provenance and auditability

Each stage records its own producer/version identifier:

* classifier: `rules-v1`
* proposal engine: `rules-v1`
* policy engine: `rules-v1`

Repeated classification, proposal, and policy evaluation are allowed.

New evaluations create new immutable historical facts rather than overwriting
prior results.

## Safety

Milestone 1 remains informational and decision-oriented only.

It does not:

* move files
* rename files
* resolve physical destination paths
* create destination directories
* create or populate `00_Revisar`
* create or populate `99_Eliminar`
* authorize deletion
* delete files
* quarantine files
* invoke a TransactionEngine
* perform filesystem mutation

Classification, proposal generation, and policy evaluation operate on
already-known in-memory state and perform no filesystem I/O.

`AUTO` is not execution.

It only means that the proposal is eligible for consideration by a future
execution layer.

## Verification

Automated verification at Milestone 1 close:

* ruff format — clean
* ruff check — passed
* mypy src — passed
* pytest — 319 passed, 9 skipped

Manual FA-006 end-to-end verification confirmed:

* classification -> proposal generation
* mapped logical destinations
* UNKNOWN/OTHER no-destination behavior
* EXECUTABLE proposal generation
* proposal confidence semantics
* physical destination remains `None`
* proposed name remains `None`
* `PROPOSAL_CREATED` persistence

FA-007 automated tests additionally verify:

* default-deny AUTO behavior
* explicit AUTO allowlist
* EXECUTABLE confidence override
* `confidence != permission`
* REVIEW persistence
* PolicyDecision domain invariants
* BLOCK is unreachable under `rules-v1`
* zero filesystem I/O

## Milestone result

File Agent can now answer:

1. What kind of file is this?
2. Where would it logically propose organizing it?
3. What does current policy permit for that proposal?

It can make those decisions deterministically, explainably, and audibly
without modifying managed user files.

Milestone 1 — Understand is complete.

## Next

FA-008 — Transaction Engine

Milestone 2 will introduce controlled filesystem mutation.

All managed-file mutations must pass through the TransactionEngine and must
preserve the safety guarantees defined in `docs/SAFETY.md`.
