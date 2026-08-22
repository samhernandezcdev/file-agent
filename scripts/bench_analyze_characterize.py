#!/usr/bin/env python
"""FA-017.7B.1 -- large-scale persistence characterization instrumentation.

Dev/perf characterization utility only -- not product code, never imported
by anything under src/file_agent/, and NOT collected by pytest (name
doesn't match test_*.py/*_test.py). Run manually:

    uv run python scripts/bench_analyze_characterize.py <mode> [n ...]

Modes:
    chunked <n> [chunk_size]   -- real analyze_managed_root, chunk-level
                                  timing + per-call record_analyzed_file
                                  latency + DB/WAL file size sampling.
    scratch <n> [chunk_size]   -- control experiment: N single-row,
                                  single-transaction commits against a
                                  trivial scratch table (same engine/
                                  PRAGMAs), chunk-level timing + size
                                  sampling -- isolates generic SQLite/WAL
                                  commit-count scaling from the real,
                                  growing domain_events/file_observations
                                  schema.
    oldpath <n>                -- benchmark-only reproduction of the
                                  PRE-FA-017.7B four-separate-commit path
                                  (record_hash_success + 3x record_event,
                                  all still-present, unmodified store
                                  methods), for causal old-vs-new
                                  comparison at the same N.
    fsonly <n>                 -- times DirectoryScanner.run() alone
                                  (pure filesystem discovery, no hashing/
                                  persistence at all) to separately
                                  measure scandir-at-scale cost.

Every mode uses disposable tempfile.mkdtemp() directories, torn down in a
finally block. Nothing is written to the repository.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import text

from file_agent import structural_safety
from file_agent.application import FileAgentApplicationService
from file_agent.classifier import FileClassifier, classification_event
from file_agent.hasher import FileHasher, HashFailure
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.policy_engine import PolicyEngine, policy_decision_event
from file_agent.proposal_engine import ProposalEngine, proposal_event
from file_agent.scanner import DirectoryScanner


def _make_env(prefix: str):
    appdata_dir = Path(tempfile.mkdtemp(prefix=f"fa-char-{prefix}-appdata-"))
    managed_dir = Path(tempfile.mkdtemp(prefix=f"fa-char-{prefix}-managed-"))
    app_paths = AppPaths.from_root(appdata_dir / "appdata")
    engine, session_factory = create_engine_and_session_factory(app_paths)
    Base.metadata.create_all(engine)
    store = FileAgentStore(session_factory)
    return appdata_dir, managed_dir, app_paths, engine, store


def _cleanup(appdata_dir: Path, managed_dir: Path, engine: object) -> None:
    engine.dispose()  # type: ignore[attr-defined]
    shutil.rmtree(appdata_dir, ignore_errors=True)
    shutil.rmtree(managed_dir, ignore_errors=True)


def _db_and_wal_sizes(app_paths: AppPaths) -> tuple[int, int]:
    db_path = app_paths.database_path
    wal_path = db_path.with_name(db_path.name + "-wal")
    db_size = db_path.stat().st_size if db_path.exists() else 0
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    return db_size, wal_size


def _percentiles(values: list[float]) -> str:
    s = sorted(values)
    n = len(s)
    p50 = s[int(n * 0.50)]
    p95 = s[min(int(n * 0.95), n - 1)]
    return f"mean={statistics.mean(s):.3f} p50={p50:.3f} p95={p95:.3f} max={s[-1]:.3f}"


def mode_chunked(n: int, chunk_size: int = 500) -> None:
    appdata_dir, managed_dir, app_paths, engine, store = _make_env("pipeline")
    try:
        for i in range(n):
            (managed_dir / f"file_{i:06d}.pdf").write_text(f"demo pdf content {i}")

        real_record_analyzed_file = store.record_analyzed_file
        latencies: list[float] = []
        chunk_rows: list[tuple[int, int, float, float, int, int, str]] = []
        chunk_start_time = [None]
        chunk_start_index = [0]
        call_index = [0]

        def _instrumented(*args: object, **kwargs: object) -> None:
            if chunk_start_time[0] is None:
                chunk_start_time[0] = time.perf_counter()
                chunk_start_index[0] = call_index[0]
            t0 = time.perf_counter()
            real_record_analyzed_file(*args, **kwargs)  # type: ignore[arg-type]
            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)
            call_index[0] += 1
            if call_index[0] % chunk_size == 0:
                elapsed = (time.perf_counter() - chunk_start_time[0]) * 1000
                db_size, wal_size = _db_and_wal_sizes(app_paths)
                chunk_lat = latencies[chunk_start_index[0] : call_index[0]]
                chunk_rows.append(
                    (
                        chunk_start_index[0] + 1,
                        call_index[0],
                        elapsed,
                        elapsed / len(chunk_lat),
                        db_size,
                        wal_size,
                        _percentiles(chunk_lat),
                    )
                )
                chunk_start_time[0] = None

        store.record_analyzed_file = _instrumented  # type: ignore[method-assign]

        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id

        real_scanner_run = DirectoryScanner.run
        scan_ms = [0.0]

        def _timed_scan(self: DirectoryScanner) -> object:
            t0 = time.perf_counter()
            result = real_scanner_run(self)
            scan_ms[0] = (time.perf_counter() - t0) * 1000
            return result

        DirectoryScanner.run = _timed_scan  # type: ignore[method-assign]
        try:
            t_total0 = time.perf_counter()
            result = service.analyze_managed_root(managed_root_id)
            total_ms = (time.perf_counter() - t_total0) * 1000
        finally:
            DirectoryScanner.run = real_scanner_run  # type: ignore[method-assign]

        persistence_ms = sum(latencies)
        compute_ms = total_ms - scan_ms[0] - persistence_ms

        print(f"=== chunked real-pipeline run: n={n} chunk_size={chunk_size} ===")
        print(
            f"successful={len(result.items)} total_ms={total_ms:.1f} ms/file={total_ms / n:.3f}"
        )
        print(
            f"phase split: scan={scan_ms[0]:.1f}ms "
            f"persistence(sum of record_analyzed_file calls)={persistence_ms:.1f}ms "
            f"compute(hash+classify+propose+policy, remainder)={compute_ms:.1f}ms"
        )
        print(
            f"{'range':>15} | {'elapsed_ms':>10} | {'ms/file':>8} | "
            f"{'db_bytes':>10} | {'wal_bytes':>10} | latency_stats_ms"
        )
        for start, end, elapsed, ms_per_file, db_size, wal_size, pct in chunk_rows:
            print(
                f"{start:>6}-{end:<7} | {elapsed:>10.1f} | {ms_per_file:>8.3f} | "
                f"{db_size:>10} | {wal_size:>10} | {pct}"
            )
    finally:
        _cleanup(appdata_dir, managed_dir, engine)


def mode_scratch(n: int, chunk_size: int = 500) -> None:
    """Control A: isolates generic SQLite/WAL commit-count scaling from
    the real, growing domain_events/file_observations schema."""
    appdata_dir = Path(tempfile.mkdtemp(prefix="fa-char-scratch-"))
    try:
        app_paths = AppPaths.from_root(appdata_dir / "appdata")
        engine, _ = create_engine_and_session_factory(app_paths)
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE scratch (id INTEGER PRIMARY KEY, payload TEXT)")
            )

        print(
            f"=== control A: scratch-table single-row commits, n={n} chunk_size={chunk_size} ==="
        )
        print(
            f"{'range':>15} | {'elapsed_ms':>10} | {'ms/commit':>9} | {'db_bytes':>10} | {'wal_bytes':>10}"
        )
        chunk_t0 = time.perf_counter()
        for i in range(n):
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO scratch (payload) VALUES (:p)"), {"p": f"row-{i}"}
                )
            if (i + 1) % chunk_size == 0:
                elapsed = (time.perf_counter() - chunk_t0) * 1000
                db_size, wal_size = _db_and_wal_sizes(app_paths)
                print(
                    f"{i + 2 - chunk_size:>6}-{i + 1:<7} | {elapsed:>10.1f} | "
                    f"{elapsed / chunk_size:>9.3f} | {db_size:>10} | {wal_size:>10}"
                )
                chunk_t0 = time.perf_counter()
        engine.dispose()
    finally:
        shutil.rmtree(appdata_dir, ignore_errors=True)


def _old_path_analyze_discovered(service, store, discovered, sandbox_root):  # type: ignore[no-untyped-def]
    """Benchmark-only reproduction of _analyze_discovered's PRE-FA-017.7B
    body -- four separate store calls (record_hash_success + 3x
    record_event) instead of the new record_analyzed_file. Uses the
    still-present, unmodified store methods and real engines. Not a
    production code path; exists only in this script for causal
    old-vs-new comparison at the same N."""
    from file_agent.application.dto import AnalysisFailure

    hash_outcome = FileHasher(sandbox_root, clock=service._clock).hash_file(discovered)
    if isinstance(hash_outcome, HashFailure):
        return AnalysisFailure(
            file_id=discovered.id,
            path=discovered.path,
            reason_code=hash_outcome.issue.issue_type.value,
        )
    store.record_hash_success(hash_outcome)

    classification = FileClassifier(clock=service._clock).classify(hash_outcome.hashed)
    store.record_event(classification_event(classification))

    proposal = ProposalEngine(clock=service._clock).propose(classification)
    store.record_event(proposal_event(proposal))

    policy_decision = PolicyEngine(clock=service._clock).evaluate(proposal)
    store.record_event(policy_decision_event(policy_decision))
    return None


def mode_oldpath(n: int, chunk_size: int = 500) -> None:
    appdata_dir, managed_dir, app_paths, engine, store = _make_env("oldpath")
    try:
        for i in range(n):
            (managed_dir / f"file_{i:06d}.pdf").write_text(f"demo pdf content {i}")

        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id
        sandbox_root = service._resolve_active_managed_root(managed_root_id)

        scan_result = DirectoryScanner(
            sandbox_root,
            managed_root_id=managed_root_id,
            clock=service._clock,
        ).run()
        store.record_scan(scan_result)

        print(f"=== old 4-commit-path reproduction: n={n} chunk_size={chunk_size} ===")
        print(
            f"{'range':>15} | {'elapsed_ms':>10} | {'ms/file':>8} | {'db_bytes':>10} | {'wal_bytes':>10}"
        )
        chunk_t0 = time.perf_counter()
        t_total0 = time.perf_counter()
        successful = 0
        for idx, discovered in enumerate(scan_result.files):
            outcome = _old_path_analyze_discovered(
                service, store, discovered, sandbox_root
            )
            if outcome is None:
                successful += 1
            if (idx + 1) % chunk_size == 0:
                elapsed = (time.perf_counter() - chunk_t0) * 1000
                db_size, wal_size = _db_and_wal_sizes(app_paths)
                print(
                    f"{idx + 2 - chunk_size:>6}-{idx + 1:<7} | {elapsed:>10.1f} | "
                    f"{elapsed / chunk_size:>8.3f} | {db_size:>10} | {wal_size:>10}"
                )
                chunk_t0 = time.perf_counter()
        total_ms = (time.perf_counter() - t_total0) * 1000
        print(
            f"successful={successful} total_ms={total_ms:.1f} ms/file={total_ms / n:.3f}"
        )
    finally:
        _cleanup(appdata_dir, managed_dir, engine)


def mode_fsonly(n: int) -> None:
    appdata_dir, managed_dir, app_paths, engine, store = _make_env("fsonly")
    try:
        for i in range(n):
            (managed_dir / f"file_{i:06d}.pdf").write_text(f"demo pdf content {i}")
        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id
        sandbox_root = service._resolve_active_managed_root(managed_root_id)

        t0 = time.perf_counter()
        scan_result = DirectoryScanner(
            sandbox_root,
            managed_root_id=managed_root_id,
            clock=service._clock,
        ).run()
        elapsed = (time.perf_counter() - t0) * 1000
        print(
            f"=== filesystem-only scan: n={n} files_discovered={len(scan_result.files)} "
            f"total_ms={elapsed:.1f} ms/file={elapsed / n:.4f} ==="
        )
    finally:
        _cleanup(appdata_dir, managed_dir, engine)


def mode_hotpath(n: int, layout: str = "flat") -> None:
    """FA-017.7B.2 Parts 3/5/6/8: times structural_safety.find_structural_
    protection and FileHasher.hash_file -- the actual real production
    functions, called directly, not reimplemented -- per real discovered
    file, with NO persistence and NO classifier/proposal/policy, isolating
    exactly the filesystem hot path _analyze_discovered exercises before
    any DB write. `layout` is "flat" (all N files in one directory) or
    "nested:<dirs>" (N files spread evenly across <dirs> subdirectories)
    -- identical total file count, per-file size, and total bytes either
    way."""
    managed_dir = Path(tempfile.mkdtemp(prefix="fa-char-hotpath-managed-"))
    appdata_dir = Path(tempfile.mkdtemp(prefix="fa-char-hotpath-appdata-"))
    try:
        if layout == "flat":
            for i in range(n):
                (managed_dir / f"file_{i:06d}.pdf").write_text(f"demo pdf content {i}")
        else:
            num_dirs = int(layout.split(":")[1])
            per_dir = n // num_dirs
            for d in range(num_dirs):
                sub = managed_dir / f"sub_{d:04d}"
                sub.mkdir()
                for i in range(per_dir):
                    (sub / f"file_{i:06d}.pdf").write_text(f"demo pdf content {d}-{i}")

        app_paths = AppPaths.from_root(appdata_dir / "appdata")
        engine, session_factory = create_engine_and_session_factory(app_paths)
        Base.metadata.create_all(engine)
        store = FileAgentStore(session_factory)
        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id
        sandbox_root = service._resolve_active_managed_root(managed_root_id)

        scan_result = DirectoryScanner(
            sandbox_root,
            managed_root_id=managed_root_id,
            clock=service._clock,
        ).run()

        structural_latencies: list[float] = []
        hash_latencies: list[float] = []
        hasher = FileHasher(sandbox_root, clock=service._clock)
        # FA-017.7B.3: use the new scan-scoped ScanStructuralContext (one
        # per hotpath run, matching how analyze_managed_root constructs
        # it) instead of the bare find_structural_protection function --
        # this is what actually exercises the shared-ancestor cache being
        # benchmarked here.
        structural_context = structural_safety.ScanStructuralContext(sandbox_root.path)
        t_total0 = time.perf_counter()
        for discovered in scan_result.files:
            t0 = time.perf_counter()
            structural_context.check_candidate(
                discovered.path, inspect_candidate_reference=True
            )
            structural_latencies.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            hasher.hash_file(discovered)
            hash_latencies.append((time.perf_counter() - t0) * 1000)
        total_ms = (time.perf_counter() - t_total0) * 1000

        print(
            f"=== hotpath: n={n} layout={layout} files_discovered={len(scan_result.files)} ==="
        )
        print(f"total_ms={total_ms:.1f} ms/file={total_ms / n:.3f}")
        print(
            f"structural_safety: {_percentiles(structural_latencies)} total_ms={sum(structural_latencies):.1f}"
        )
        print(
            f"hash_file:         {_percentiles(hash_latencies)} total_ms={sum(hash_latencies):.1f}"
        )
        engine.dispose()
    finally:
        shutil.rmtree(appdata_dir, ignore_errors=True)
        shutil.rmtree(managed_dir, ignore_errors=True)


def mode_purelogic(n: int) -> None:
    """Part 4: pure in-memory classifier/proposal/policy cost -- no
    filesystem access, no persistence -- reuses one real, actually-hashed
    DiscoveredFile as the input template for all N iterations, to prove
    or refute whether these engines' own cost changes with N."""
    managed_dir = Path(tempfile.mkdtemp(prefix="fa-char-purelogic-managed-"))
    appdata_dir = Path(tempfile.mkdtemp(prefix="fa-char-purelogic-appdata-"))
    try:
        (managed_dir / "template.pdf").write_text("demo pdf content")
        app_paths = AppPaths.from_root(appdata_dir / "appdata")
        engine, session_factory = create_engine_and_session_factory(app_paths)
        Base.metadata.create_all(engine)
        store = FileAgentStore(session_factory)
        service = FileAgentApplicationService(app_paths, store)
        managed_root_id = service.add_managed_root(managed_dir).id
        sandbox_root = service._resolve_active_managed_root(managed_root_id)
        scan_result = DirectoryScanner(
            sandbox_root,
            managed_root_id=managed_root_id,
            clock=service._clock,
        ).run()
        discovered = scan_result.files[0]
        hash_outcome = FileHasher(sandbox_root, clock=service._clock).hash_file(
            discovered
        )
        assert not isinstance(hash_outcome, HashFailure)

        classify_lat: list[float] = []
        propose_lat: list[float] = []
        policy_lat: list[float] = []
        t_total0 = time.perf_counter()
        for _ in range(n):
            t0 = time.perf_counter()
            classification = FileClassifier(clock=service._clock).classify(
                hash_outcome.hashed
            )
            classify_lat.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            proposal = ProposalEngine(clock=service._clock).propose(classification)
            propose_lat.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            PolicyEngine(clock=service._clock).evaluate(proposal)
            policy_lat.append((time.perf_counter() - t0) * 1000)
        total_ms = (time.perf_counter() - t_total0) * 1000

        print(
            f"=== purelogic: n={n} (classify+propose+policy, no filesystem/persistence) ==="
        )
        print(f"total_ms={total_ms:.1f} ms/iter={total_ms / n:.4f}")
        print(f"classify: {_percentiles(classify_lat)}")
        print(f"propose:  {_percentiles(propose_lat)}")
        print(f"policy:   {_percentiles(policy_lat)}")
        engine.dispose()
    finally:
        shutil.rmtree(appdata_dir, ignore_errors=True)
        shutil.rmtree(managed_dir, ignore_errors=True)


def mode_sizedim(n: int = 1000, size_bytes: int = 100_000) -> None:
    """Part 9: tiny-file vs larger-file hash-only timing at the same N --
    separates metadata/syscall overhead (expected dominant for tiny
    files) from read/hash throughput (expected dominant for larger
    files)."""
    for label, content_size in (("tiny", 20), (f"{size_bytes}B", size_bytes)):
        managed_dir = Path(tempfile.mkdtemp(prefix=f"fa-char-sizedim-{label}-managed-"))
        appdata_dir = Path(tempfile.mkdtemp(prefix=f"fa-char-sizedim-{label}-appdata-"))
        try:
            payload = b"x" * content_size
            for i in range(n):
                (managed_dir / f"file_{i:06d}.bin").write_bytes(payload)
            app_paths = AppPaths.from_root(appdata_dir / "appdata")
            engine, session_factory = create_engine_and_session_factory(app_paths)
            Base.metadata.create_all(engine)
            store = FileAgentStore(session_factory)
            service = FileAgentApplicationService(app_paths, store)
            managed_root_id = service.add_managed_root(managed_dir).id
            sandbox_root = service._resolve_active_managed_root(managed_root_id)
            scan_result = DirectoryScanner(
                sandbox_root,
                managed_root_id=managed_root_id,
                clock=service._clock,
            ).run()
            hasher = FileHasher(sandbox_root, clock=service._clock)
            t0 = time.perf_counter()
            for discovered in scan_result.files:
                hasher.hash_file(discovered)
            elapsed = (time.perf_counter() - t0) * 1000
            total_mb = (n * content_size) / (1024 * 1024)
            mbps = total_mb / (elapsed / 1000) if elapsed > 0 else float("inf")
            print(
                f"=== sizedim: n={n} label={label} content_bytes={content_size} "
                f"total_ms={elapsed:.1f} ms/file={elapsed / n:.4f} throughput_MBps={mbps:.1f} ==="
            )
            engine.dispose()
        finally:
            shutil.rmtree(appdata_dir, ignore_errors=True)
            shutil.rmtree(managed_dir, ignore_errors=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "hotpath":
        n = int(sys.argv[2])
        layout = sys.argv[3] if len(sys.argv) > 3 else "flat"
        mode_hotpath(n, layout)
    elif mode == "purelogic":
        mode_purelogic(int(sys.argv[2]))
    elif mode == "sizedim":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
        size_bytes = int(sys.argv[3]) if len(sys.argv) > 3 else 100_000
        mode_sizedim(n, size_bytes)
    else:
        n = int(sys.argv[2])
        chunk = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        if mode == "chunked":
            mode_chunked(n, chunk)
        elif mode == "scratch":
            mode_scratch(n, chunk)
        elif mode == "oldpath":
            mode_oldpath(n, chunk)
        elif mode == "fsonly":
            mode_fsonly(n)
        else:
            raise SystemExit(f"unknown mode: {mode}")
