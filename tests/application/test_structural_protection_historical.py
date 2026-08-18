"""FA-016 round-4 Major 1 regression: a DiscoveredFile/PolicyDecision that
predates this feature (or was otherwise persisted before its owning
directory was recognized as hard-excluded) is protected by the LIVE
re-check with ZERO new scan required -- covers the review's required test
matrix item C, for each of node_modules/.venv/.git."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
)
from file_agent.application.dto import AnalysisFailure, ApplicationRejectionReason
from file_agent.application.managed_roots import ManagedRootUnavailable
from file_agent.application.organization_plan import PlanStatus
from file_agent.classifier import FileClassifier, classification_event
from file_agent.domain import (
    DiscoveredFile,
    DomainEvent,
    EntityType,
    EventType,
    ScanRun,
    ScanStatus,
)
from file_agent.hasher import FileHasher, HashSuccess
from file_agent.persistence import FileAgentStore
from file_agent.policy_engine import PolicyEngine, policy_decision_event
from file_agent.proposal_engine import ProposalEngine, proposal_event
from file_agent.scanner import SandboxRoot
from file_agent.scanner.result import ScanResult


def _simulate_pre_fa016_policy_decision(
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    managed_root_id: UUID,
    relative_dir: str,
    filename: str,
    content: bytes,
) -> UUID:
    """Directly persists a DiscoveredFile at a path the scanner would now
    prune (it never went through scan-time structural pruning, exactly like
    genuinely pre-FA-016 data would not have), then runs it through
    FileHasher/FileClassifier/ProposalEngine/PolicyEngine manually --
    bypassing _analyze_discovered's own new structural gate entirely, since
    the whole point is to construct the state AS IF that gate never
    existed. Returns the resulting policy_decision_id."""
    directory = sandbox_root.path / relative_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(content)
    st = path.stat()

    scan_run = ScanRun(root_path=sandbox_root.path, started_at=datetime.now(UTC))
    scan_run = scan_run.evolve(
        status=ScanStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        files_discovered=1,
    )
    discovered = DiscoveredFile(
        path=path,
        size_bytes=st.st_size,
        created_at=datetime.fromtimestamp(st.st_ctime, tz=UTC),
        modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        discovered_by_scan_id=scan_run.id,
        managed_root_id=managed_root_id,
    )
    discovered_event = DomainEvent(
        event_type=EventType.FILE_DISCOVERED,
        entity_type=EntityType.FILE,
        entity_id=discovered.id,
        payload={"scan_id": str(scan_run.id), "path": str(discovered.path)},
    )
    store.record_scan(
        ScanResult(
            scan_run=scan_run,
            files=(discovered,),
            events=(discovered_event,),
            issues=(),
            protected_trees=(),
        )
    )

    hash_outcome = FileHasher(sandbox_root).hash_file(discovered)
    assert isinstance(hash_outcome, HashSuccess)
    store.record_hash_success(hash_outcome)

    classification = FileClassifier().classify(hash_outcome.hashed)
    store.record_event(classification_event(classification))

    proposal = ProposalEngine().propose(classification)
    store.record_event(proposal_event(proposal))

    policy_decision = PolicyEngine().evaluate(proposal)
    store.record_event(policy_decision_event(policy_decision))

    return policy_decision.id


@pytest.mark.parametrize("relative_dir", ["node_modules", ".venv", ".git/objects"])
def test_historical_file_under_hard_exclusion_analyze_file_rejects(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    store: FileAgentStore,
    relative_dir: str,
) -> None:
    policy_decision_id = _simulate_pre_fa016_policy_decision(
        store, sandbox_root, managed_root_id, relative_dir, "loose_object.pdf", b"x"
    )
    from file_agent.application import queries

    policy_decision = queries.find_policy_decision(store, policy_decision_id)
    assert not isinstance(policy_decision, queries.LookupFailure)
    discovered = store.get_discovered_file(policy_decision.file_id)
    assert discovered is not None

    result = service.analyze_file(discovered.id)

    assert isinstance(result, AnalysisFailure)
    assert result.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value


@pytest.mark.parametrize("relative_dir", ["node_modules", ".venv", ".git/objects"])
def test_historical_file_under_hard_exclusion_plan_shows_protected(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    store: FileAgentStore,
    relative_dir: str,
) -> None:
    policy_decision_id = _simulate_pre_fa016_policy_decision(
        store, sandbox_root, managed_root_id, relative_dir, "loose_object.pdf", b"x"
    )

    plan = service.create_organization_plan([policy_decision_id])

    assert not isinstance(plan, ManagedRootUnavailable)
    assert len(plan.items) == 1
    assert plan.items[0].status is PlanStatus.PROTECTED


@pytest.mark.parametrize("relative_dir", ["node_modules", ".venv", ".git/objects"])
def test_historical_file_under_hard_exclusion_apply_rejects_zero_mutation(
    service: FileAgentApplicationService,
    managed_root_id: UUID,
    sandbox_root: SandboxRoot,
    store: FileAgentStore,
    relative_dir: str,
) -> None:
    policy_decision_id = _simulate_pre_fa016_policy_decision(
        store, sandbox_root, managed_root_id, relative_dir, "loose_object.pdf", b"x"
    )
    original_path = sandbox_root.path / relative_dir / "loose_object.pdf"

    single = service.apply_item(policy_decision_id)
    assert single.status is ApplicationOutcomeStatus.REJECTED
    assert single.reason_code == ApplicationRejectionReason.STRUCTURALLY_PROTECTED.value
    assert original_path.exists()

    batch = service.apply_items([policy_decision_id])
    assert not isinstance(batch, ManagedRootUnavailable)
    assert batch.items[0].status.value == "not_applied"
    assert original_path.exists()
