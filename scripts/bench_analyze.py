#!/usr/bin/env python
"""FA-017.7B -- analyze pipeline persistence-cost benchmark.

Dev/perf utility only -- not product code, never imported by anything
under src/file_agent/, and NOT collected by pytest (this file's name
doesn't match pytest's test_*.py/*_test.py discovery pattern, matching
this repo's other scripts/ utilities). Run manually:

    uv run python scripts/bench_analyze.py

Exercises FileAgentApplicationService.analyze_managed_root() end to end
against real small files, a real SQLite engine with the app's normal WAL/
busy_timeout PRAGMAs, and disposable temp directories that are created
and torn down entirely within this process -- nothing is written to the
repository, no fixture files are committed.

This re-runs the exact methodology FA-017.7 Design/Audit Round 1 used to
establish the pre-optimization baseline (100/500/1,000 files; 5,000 added
here since the post-optimization per-file cost makes it feasible in
reasonable wall-clock time), so the printed numbers are directly
comparable to that baseline:

    100:   1,861.8 ms total, 18.618 ms/file
    500:   9,112.4 ms total, 18.225 ms/file
    1,000: 19,183.3 ms total, 19.183 ms/file

against FA-017.7B's new record_analyzed_file (1 commit/file instead of 4).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from file_agent.application import FileAgentApplicationService
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base


def _bench_one(n: int) -> None:
    appdata_dir = Path(tempfile.mkdtemp(prefix="fa-bench-appdata-"))
    managed_dir = Path(tempfile.mkdtemp(prefix="fa-bench-managed-"))
    try:
        for i in range(n):
            (managed_dir / f"file_{i:06d}.pdf").write_text(f"demo pdf content {i}")

        app_paths = AppPaths.from_root(appdata_dir / "appdata")
        engine, session_factory = create_engine_and_session_factory(app_paths)
        Base.metadata.create_all(engine)
        store = FileAgentStore(session_factory)

        commit_count = {"record_analyzed_file": 0, "record_scan": 0}
        real_record_analyzed_file = store.record_analyzed_file
        real_record_scan = store.record_scan

        def _counted_record_analyzed_file(*args: object, **kwargs: object) -> None:
            commit_count["record_analyzed_file"] += 1
            real_record_analyzed_file(*args, **kwargs)  # type: ignore[arg-type]

        def _counted_record_scan(*args: object, **kwargs: object) -> None:
            commit_count["record_scan"] += 1
            real_record_scan(*args, **kwargs)  # type: ignore[arg-type]

        store.record_analyzed_file = _counted_record_analyzed_file  # type: ignore[method-assign]
        store.record_scan = _counted_record_scan  # type: ignore[method-assign]

        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id

        t0 = time.perf_counter()
        result = service.analyze_managed_root(managed_root_id)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        engine.dispose()

        successful = len(result.items)
        print(
            f"{n:>7} | {elapsed_ms:>10.1f} | {elapsed_ms / n:>9.3f} | "
            f"{successful:>10} | {commit_count['record_scan']:>13} | "
            f"{commit_count['record_analyzed_file']:>19}"
        )
    finally:
        shutil.rmtree(appdata_dir, ignore_errors=True)
        shutil.rmtree(managed_dir, ignore_errors=True)


def main() -> None:
    print(
        "FA-017.7B analyze-pipeline benchmark (post-optimization: record_analyzed_file)"
    )
    print(
        f"{'N files':>7} | {'total_ms':>10} | {'ms/file':>9} | "
        f"{'successful':>10} | {'scan_commits':>13} | {'analyzed_file_commits':>19}"
    )
    for n in (100, 500, 1_000, 5_000):
        _bench_one(n)


if __name__ == "__main__":
    main()
