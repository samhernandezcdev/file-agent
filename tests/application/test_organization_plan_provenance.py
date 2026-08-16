"""OrganizationPlan / preview (FA-013): analysis-generation lineage and
staleness semantics -- the two invariants inherited most directly from
FA-012's own provenance discipline."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from file_agent.application import (
    ApplicationOutcomeStatus,
    FileAgentApplicationService,
    PlanStatus,
)
from file_agent.domain import (
    DestinationCategory,
    FileCategory,
    FileProposal,
    PolicyDecision,
    PolicyOutcome,
)
from file_agent.persistence import FileAgentStore
from file_agent.policy_engine import policy_decision_event
from file_agent.proposal_engine import proposal_event
from file_agent.scanner import SandboxRoot


def test_plan_for_older_generation_uses_its_own_snapshot_never_the_latest(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """Strengthened per round-3 correction 5: create generation 1, modify
    the file, create generation 2, build a plan explicitly for generation
    1's policy_decision_id -- the resulting item must reflect generation
    1's own proposal/destination, and must never reference generation 2 at
    all. There is no lookup-by-file_id anywhere in the planner that could
    silently substitute the newer generation."""
    source = make_source_file(
        "report.txt", content=b"generation one content, classified as documents"
    )
    first = service.analyze_scan()
    old_item = first.items[0]

    # Generation 2: different content, still a DOCUMENT (same destination
    # category) -- what matters here is P1/D1's OWN ids stay pinned, not
    # that the destination category itself differs.
    source.write_bytes(b"generation two, totally different content")
    second = service.analyze_file(old_item.file_id)
    assert second.proposal_id != old_item.proposal_id
    assert second.policy_decision_id != old_item.policy_decision_id

    plan = service.create_organization_plan([old_item.policy_decision_id])

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.proposal_id == old_item.proposal_id
    assert item.policy_decision_id == old_item.policy_decision_id
    assert item.destination_category == old_item.proposed_destination_category
    if old_item.proposed_destination_category is not None:
        assert item.destination_path == (sandbox_root.path / "Documents" / source.name)
    # no reference anywhere to generation 2's own ids
    assert item.proposal_id != second.proposal_id
    assert item.policy_decision_id != second.policy_decision_id


def test_plan_never_mixes_older_generation_ids_with_a_newer_generations_category_or_destination(
    service: FileAgentApplicationService,
    store: FileAgentStore,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    """Direct regression test for the provenance-review concern: hand-builds
    two genuinely conflicting analysis generations for the SAME file_id --
    generation 1 classified as DOCUMENT -> DOCUMENTS, generation 2 as
    IMAGE -> IMAGES -- and proves create_organization_plan([D1]) reflects
    generation 1's category/destination_category/policy_outcome/proposal_id
    exclusively. This would fail if the planner ever read category/
    destination_category/policy_outcome from anything other than the exact
    policy_decision_id's own lineage (e.g. a "latest proposal for this
    file_id" lookup)."""
    source = make_source_file("report.txt", content=b"generation one content")
    file_id = service.analyze_scan().items[0].file_id
    now = datetime.now(UTC)

    proposal_1 = FileProposal(
        file_id=file_id,
        proposed_destination_category=DestinationCategory.DOCUMENTS,
        category=FileCategory.DOCUMENT,
        confidence=0.9,
        source_classification_confidence=0.9,
        source_classifier_id="rules-v1",
        reasons=("generation one",),
        proposal_engine_id="rules-v1",
        expected_size=10,
        expected_created_at=now,
        expected_modified_at=now,
        sha256="a" * 64,
    )
    policy_1 = PolicyDecision(
        proposal_id=proposal_1.id,
        file_id=file_id,
        decision=PolicyOutcome.AUTO,
        reasons=("generation one",),
        policy_engine_id="policy-v1",
        source_category=FileCategory.DOCUMENT,
        destination_category=DestinationCategory.DOCUMENTS,
        proposal_confidence=0.9,
        proposal_engine_id="rules-v1",
    )
    store.record_event(proposal_event(proposal_1))
    store.record_event(policy_decision_event(policy_1))

    # A second, genuinely conflicting generation for the SAME file_id --
    # different category, different destination, different policy_outcome.
    proposal_2 = FileProposal(
        file_id=file_id,
        proposed_destination_category=DestinationCategory.IMAGES,
        category=FileCategory.IMAGE,
        confidence=0.9,
        source_classification_confidence=0.9,
        source_classifier_id="rules-v1",
        reasons=("generation two",),
        proposal_engine_id="rules-v1",
        expected_size=999,
        expected_created_at=now,
        expected_modified_at=now,
        sha256="b" * 64,
    )
    policy_2 = PolicyDecision(
        proposal_id=proposal_2.id,
        file_id=file_id,
        decision=PolicyOutcome.REVIEW,
        reasons=("generation two",),
        policy_engine_id="policy-v1",
        source_category=FileCategory.IMAGE,
        destination_category=DestinationCategory.IMAGES,
        proposal_confidence=0.9,
        proposal_engine_id="rules-v1",
    )
    store.record_event(proposal_event(proposal_2))
    store.record_event(policy_decision_event(policy_2))

    plan = service.create_organization_plan([policy_1.id])

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.proposal_id == proposal_1.id
    assert item.policy_decision_id == policy_1.id
    assert item.category is FileCategory.DOCUMENT
    assert item.destination_category is DestinationCategory.DOCUMENTS
    assert item.policy_outcome is PolicyOutcome.AUTO
    assert item.destination_path == sandbox_root.path / "Documents" / "report.txt"
    # source_path/filename come from the one immutable fact
    # (FileObservationRow.path, never updated post-insert) -- identical for
    # both generations by construction, so asserting it here documents that
    # invariant rather than proving generation selection on its own.
    assert item.source_path == source
    assert item.filename == "report.txt"
    # nothing here traces to generation 2 at all
    assert item.proposal_id != proposal_2.id
    assert item.policy_decision_id != policy_2.id
    assert item.category is not FileCategory.IMAGE
    assert item.destination_category is not DestinationCategory.IMAGES


def test_planner_never_looks_up_by_file_id() -> None:
    """Structural confirmation, complementing the behavioral regression
    test above: application/planner.py's only lookup path is
    policy_decision_id -> PolicyDecision.proposal_id -> FileProposal.
    get_discovered_file(policy_decision.file_id) is called exactly once,
    purely for path/filename display after the generation is already
    pinned by policy_decision_id -- never used to select "the" proposal
    for a file, and there is no "latest"-flavored helper anywhere in the
    module."""
    import ast
    from pathlib import Path as PathlibPath

    planner_file = (
        PathlibPath(__file__).resolve().parents[2]
        / "src"
        / "file_agent"
        / "application"
        / "planner.py"
    )
    source = planner_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(planner_file))

    # No function/variable name anywhere in the module suggests a
    # "latest"-flavored selection helper (the docstring itself explicitly
    # documents the ABSENCE of such logic, so only identifiers -- not
    # prose -- are checked here).
    identifier_names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    assert not any("latest" in name.lower() for name in identifier_names)
    discovered_file_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_discovered_file"
    ]
    assert len(discovered_file_calls) == 1
    (call,) = discovered_file_calls
    (arg,) = call.args
    assert isinstance(arg, ast.Attribute)
    assert arg.attr == "file_id"
    assert isinstance(arg.value, ast.Name)
    assert arg.value.id == "policy_decision"


def test_stale_ready_plan_is_immutable_and_apply_is_safely_rejected(
    service: FileAgentApplicationService,
    sandbox_root: SandboxRoot,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("invoice.pdf", content=b"pdf")
    item = service.analyze_scan().items[0]

    plan = service.create_organization_plan([item.policy_decision_id])
    assert plan.items[0].status is PlanStatus.READY

    # Filesystem changes AFTER the plan was built.
    (sandbox_root.path / "Documents" / "invoice.pdf").write_bytes(b"created later")

    # The plan object itself never changes -- it is frozen.
    assert plan.items[0].status is PlanStatus.READY

    # Applying now is safely rejected by TransactionEngine's own live check
    # -- staleness is a timing gap, not a rules gap (both layers use the
    # same destination.inspect_destination).
    result = service.apply_item(item.policy_decision_id)
    assert result.status is ApplicationOutcomeStatus.REJECTED
    assert result.reason_code == "destination_already_exists"
