"""FA-017 desktop sidecar API -- the narrow, presentation-facing facade
between the Tauri/Rust desktop host and FileAgent's Python core.

=== Trust boundary ===

Every command handler (handlers.py) calls exactly one public method on
FileAgentApplicationService (file_agent.application) and nothing else in
the engine layer. This package must never:

- import file_agent.managed_fs
- construct TransactionEngine/RecoveryEngine or call their internals
- construct SandboxRoot directly on caller-supplied input
- construct ExecutionAuthorization
- reimplement file_agent.structural_safety's checks
- mutate persistence directly, bypassing FileAgentApplicationService

See tests/desktop_api/test_dependency_boundary.py for the AST guardrail
enforcing this statically, and application/__init__.py's own docstring for
the trust boundary this package sits behind, never around.

=== Wire contract ===

protocol.py owns the NDJSON framing, the closed 14-command/retry-safety
manifest (commands.json), and the single sanctioned stdout writer.
views.py owns the presentation-facing Pydantic View DTOs -- the ONLY
shapes ever sent to the frontend; no internal authorization/domain object
is ever exposed as transport authority. dispatcher.py + handlers.py own
command execution. __main__.py is the actual sidecar process entrypoint
(`python -m file_agent.desktop_api`) implementing the reader/worker
threads and the process-wide fatal-transport-failure lifecycle documented
in the FA-017 design plan (Round 7).
"""
