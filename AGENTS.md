# AGENTS.md

## Project

File Agent is a local-first Windows file organization agent.

The system is being developed incrementally through numbered FA tickets and milestones.

## Required context

Before designing or modifying code, read:

1. `docs/SAFETY.md`
2. `docs/ARCHITECTURE.md`
3. the latest closed milestone summary under `docs/milestones/`
4. the current ticket specification

Historical reviews are not mandatory context for normal development.

Read a historical review only when:

* modifying the subsystem introduced by that ticket,
* investigating an existing architectural decision,
* performing a regression or security review involving that subsystem.

Do not modify closed-ticket reviews.

## Safety rules

`docs/SAFETY.md` is authoritative.

In particular:

* managed user files must remain read-only until the TransactionEngine milestone explicitly introduces mutation;
* persistence may write only application-owned state;
* no LLM or classifier may directly mutate the filesystem;
* future destructive actions must remain auditable and reversible.

If a ticket conflicts with `docs/SAFETY.md`, stop and surface the conflict rather than weakening the safety rule.

## Development workflow

For each FA ticket:

1. design first;
2. review architectural decisions;
3. implement only the approved scope;
4. run formatting, linting, typing, and tests;
5. perform adversarial review;
6. remediate blocking findings;
7. close and tag the ticket.

Do not begin the next FA ticket while the current ticket has unresolved blocking findings.

## Scope discipline

Do not implement future-ticket functionality early.

Avoid speculative abstractions unless the current ticket requires them.

Prefer small explicit interfaces over general frameworks.

## Domain boundaries

The current architecture separates:

* domain models;
* read-only filesystem observation;
* hashing;
* persistence;
* future classification/policy;
* future filesystem mutation.

Do not bypass these boundaries for convenience.

All future managed-file mutations must eventually flow through the TransactionEngine.

## Persistence

SQLite is application-owned state.

The database location must come from explicitly configured application-data storage and must never be derived from managed file paths.

Alembic owns production schema evolution.

`Base.metadata.create_all()` is test-only.

## Testing expectations

Every ticket must include tests for:

* normal behavior;
* boundary conditions;
* failure behavior;
* relevant safety invariants.

Filesystem-sensitive behavior should use real temporary files/directories when practical.

Mocks should be narrow and used only when the required state cannot be reproduced deterministically.

## Quality gates

Before declaring a ticket complete:

```text
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest -v
```

All must pass except explicitly documented platform/privilege-dependent skips.

## Historical milestones

Milestone summaries describe the capabilities and guarantees that are considered closed.

Do not silently reinterpret or weaken a closed milestone guarantee in later work.
