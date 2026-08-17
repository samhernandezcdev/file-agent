"""Review-write serialization is scoped to the shared FileAgentStore, not to
any one FileAgentApplicationService instance (round-3 correction): two
service objects wrapping the SAME store must share the SAME lock, so a
check-then-record-then-persist race between them cannot both succeed."""

import threading
from collections.abc import Callable
from pathlib import Path

from file_agent.application import ApplicationOutcomeStatus, FileAgentApplicationService
from file_agent.application.service import _review_lock_for
from file_agent.domain import EventType
from file_agent.persistence import AppPaths, FileAgentStore
from file_agent.scanner import SandboxRoot


def test_two_services_on_the_same_store_share_the_same_lock(
    sandbox_root: SandboxRoot, app_paths: AppPaths, store: FileAgentStore
) -> None:
    service_a = FileAgentApplicationService(app_paths, store)
    service_b = FileAgentApplicationService(app_paths, store)

    assert service_a._review_lock is service_b._review_lock
    assert service_a._review_lock is _review_lock_for(store)


def test_two_services_on_different_stores_get_different_locks(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    tmp_path: Path,
) -> None:
    from file_agent.persistence import create_engine_and_session_factory
    from file_agent.persistence.orm import Base

    other_config = AppPaths.from_root(tmp_path / "other_store_appdata")
    other_engine, other_session_factory = create_engine_and_session_factory(
        other_config
    )
    Base.metadata.create_all(other_engine)
    other_store = FileAgentStore(other_session_factory)
    try:
        service_a = FileAgentApplicationService(app_paths, store)
        service_b = FileAgentApplicationService(app_paths, other_store)
        assert service_a._review_lock is not service_b._review_lock
    finally:
        other_engine.dispose()


def test_concurrent_approve_and_skip_across_two_services_never_both_succeed(
    sandbox_root: SandboxRoot,
    app_paths: AppPaths,
    store: FileAgentStore,
    make_source_file: Callable[..., Path],
) -> None:
    make_source_file("app.exe", content=b"exe content")
    seed_service = FileAgentApplicationService(app_paths, store)
    managed_root_id = seed_service.add_managed_root(sandbox_root.path).id
    item = seed_service.analyze_managed_root(managed_root_id).items[0]

    service_a = FileAgentApplicationService(app_paths, store)
    service_b = FileAgentApplicationService(app_paths, store)

    results: list[object] = [None, None]

    def _approve() -> None:
        results[0] = service_a.approve_review(item.policy_decision_id)

    def _skip() -> None:
        results[1] = service_b.skip_review(item.policy_decision_id)

    thread_a = threading.Thread(target=_approve)
    thread_b = threading.Thread(target=_skip)
    thread_a.start()
    thread_b.start()
    thread_a.join()
    thread_b.join()

    statuses = [r.status for r in results]  # type: ignore[attr-defined]
    assert statuses.count(ApplicationOutcomeStatus.SUCCEEDED) == 1
    assert statuses.count(ApplicationOutcomeStatus.REJECTED) == 1
    rejected = next(r for r in results if r.status is ApplicationOutcomeStatus.REJECTED)  # type: ignore[attr-defined]
    assert rejected.reason_code == "already_reviewed"  # type: ignore[attr-defined]

    all_review_events = store.list_events_by_type(EventType.HUMAN_REVIEW_RECORDED)
    matching = [
        e
        for e in all_review_events
        if e.payload.get("policy_decision_id") == str(item.policy_decision_id)
    ]
    assert len(matching) == 1
