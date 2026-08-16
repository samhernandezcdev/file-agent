#!/usr/bin/env python
"""DEV-DEMO-001 -- OrganizationPlan terminal preview.

Developer/demo utility only -- not product code, not part of the FA-013
architecture, never imported by anything under src/file_agent/. Exercises
FileAgentApplicationService's real public API end-to-end:

    seed fixtures -> analyze_scan() -> create_organization_plan(ids) -> render

to prove that API is sufficient to drive a future UI. Never calls a lower-
level engine directly, never calls apply_item, never moves a real user file.
Everything happens inside a dedicated, demo-owned directory
(<repo>/.demo/fileagent-preview/) that this script alone creates and may
delete -- see main()'s docstring for why that recursive delete is safe here
and does not belong in file_agent's own production code.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from rich.console import Console
from rich.table import Table
from sqlalchemy import Engine

from file_agent.application import (
    AnalyzedItem,
    FileAgentApplicationService,
    OrganizationPlan,
    OrganizationPlanItem,
    PlanStatus,
)
from file_agent.destination import PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY
from file_agent.domain import PolicyOutcome
from file_agent.persistence import (
    AppPaths,
    FileAgentStore,
    create_engine_and_session_factory,
)
from file_agent.persistence.orm import Base
from file_agent.presentation import es
from file_agent.scanner import SandboxRoot

DEMO_ROOT = Path(__file__).resolve().parent.parent / ".demo" / "fileagent-preview"
SANDBOX_DIRNAME = "sandbox"
APPDATA_DIRNAME = "appdata"

_STATUS_SECTIONS: tuple[tuple[PlanStatus, str], ...] = (
    (PlanStatus.READY, "READY TO ORGANIZE"),
    (PlanStatus.REVIEW_REQUIRED, "REVIEW REQUIRED"),
    (PlanStatus.CONFLICT, "CONFLICTS"),
    (PlanStatus.SKIPPED, "SKIPPED"),
    (PlanStatus.BLOCKED, "BLOCKED"),
    (PlanStatus.INVALID, "INVALID"),
    (PlanStatus.NO_ACTION, "NO ACTION"),
)


def _seed_fixtures(sandbox_path: Path) -> None:
    """Harmless, small, deterministic byte/text fixtures only -- nothing is
    ever executed. One configured physical directory per DestinationCategory
    is pre-created (matching how a real, already-organized sandbox would
    look), plus a pre-existing file at the exact path the "report.pdf"
    fixture would be moved to, to deterministically produce a CONFLICT
    item -- never resolved, never renamed, by this script or the product."""
    for directory in PHYSICAL_DIRECTORY_FOR_DESTINATION_CATEGORY.values():
        (sandbox_path / directory).mkdir(parents=True, exist_ok=True)

    (sandbox_path / "invoice.pdf").write_bytes(b"demo pdf content -- invoice")
    (sandbox_path / "photo.jpg").write_bytes(b"demo jpg bytes -- not a real image")
    (sandbox_path / "archive.zip").write_bytes(b"demo zip bytes -- not a real archive")
    (sandbox_path / "script.py").write_text("# demo python fixture\nprint('hello')\n")
    (sandbox_path / "setup.exe").write_bytes(b"demo exe bytes -- never executed")
    (sandbox_path / "mystery.xyz123").write_bytes(b"unknown extension fixture")

    # The conflict fixture: report.pdf would resolve to Documents/report.pdf,
    # which we deliberately pre-occupy with different content.
    (sandbox_path / "report.pdf").write_bytes(
        b"demo pdf content -- the one being organized"
    )
    (sandbox_path / "Documents" / "report.pdf").write_bytes(
        b"demo pdf content -- already present at the destination"
    )


def _snapshot(sandbox_path: Path) -> dict[Path, bytes]:
    """Read-only content snapshot of every managed file, keyed by path --
    used only to prove OrganizationPlan generation mutates nothing."""
    return {
        path: path.read_bytes()
        for path in sorted(sandbox_path.rglob("*"))
        if path.is_file()
    }


def _build_service(
    sandbox_root: SandboxRoot, app_paths: AppPaths
) -> tuple[FileAgentApplicationService, Engine]:
    """Returns the SQLAlchemy Engine alongside the service so the caller can
    dispose() it before any cleanup -- on Windows, an undisposed engine
    holds the sqlite file open, which would otherwise make the final
    shutil.rmtree(DEMO_ROOT) fail with PermissionError."""
    engine, session_factory = create_engine_and_session_factory(app_paths)
    Base.metadata.create_all(engine)
    store = FileAgentStore(session_factory)
    return FileAgentApplicationService(sandbox_root, app_paths, store), engine


def _relative(path: Path | None, root: Path) -> str:
    if path is None:
        return "—"
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _render_item_table(
    console: Console,
    items: Sequence[OrganizationPlanItem],
    root: Path,
    *,
    lang: str,
) -> None:
    table = Table(show_lines=False, expand=False)
    table.add_column("Filename")
    table.add_column("Source")
    table.add_column("Category")
    table.add_column("Destination")
    table.add_column("Policy")
    table.add_column("Review")
    table.add_column("Reason")

    for item in items:
        if lang == "es":
            message = es.plan_item_message(item)
            reason = f"{message.title}: {message.detail}"
        else:
            reason = (
                f"{item.reason_code.value}: {item.reason}" if item.reason_code else "—"
            )
        table.add_row(
            item.filename,
            _relative(item.source_path, root),
            item.category.value,
            _relative(item.destination_path, root),
            item.policy_outcome.value,
            item.human_review_outcome.value if item.human_review_outcome else "—",
            reason,
        )
    console.print(table)


def render_plan(
    console: Console,
    plan: OrganizationPlan,
    sandbox_path: Path,
    heading: str = "FILEAGENT — ORGANIZATION PREVIEW",
    *,
    lang: str = "en",
) -> None:
    console.rule(f"[bold]{heading}[/bold]")
    console.print(f"root path: {sandbox_path}")
    console.print(f"analyzed files: {len(plan.items)}")
    console.print()

    by_status: dict[PlanStatus, list[OrganizationPlanItem]] = {
        status: [] for status in PlanStatus
    }
    for item in plan.items:
        by_status[item.status].append(item)

    for status, title in _STATUS_SECTIONS:
        items = by_status[status]
        if not items:
            continue
        section_title = es.plan_status_label(status) if lang == "es" else title
        console.print(f"[bold]{section_title}[/bold] ({len(items)})")
        _render_item_table(console, items, sandbox_path, lang=lang)
        console.print()

    if plan.issues:
        console.print(f"[bold]ISSUES[/bold] ({len(plan.issues)})")
        issue_table = Table(show_lines=False, expand=False)
        issue_table.add_column("policy_decision_id")
        issue_table.add_column("reason_code")
        issue_table.add_column("detail")
        for issue in plan.issues:
            issue_table.add_row(
                str(issue.policy_decision_id), issue.reason_code, issue.detail
            )
        console.print(issue_table)
        console.print()

    summary = plan.summary
    summary_table = Table(title="Summary", show_header=False)
    summary_table.add_column("field")
    summary_table.add_column("count", justify="right")
    summary_table.add_row("Total", str(summary.files_total))
    summary_table.add_row("Ready", str(summary.ready))
    summary_table.add_row("Review required", str(summary.review_required))
    summary_table.add_row("Conflicts", str(summary.conflicts))
    summary_table.add_row("Invalid", str(summary.invalid))
    summary_table.add_row("Blocked", str(summary.blocked))
    summary_table.add_row("Skipped", str(summary.skipped))
    summary_table.add_row("No action", str(summary.no_action))
    summary_table.add_row("Issues", str(summary.issues))
    console.print(summary_table)


def _approve_review_items(
    service: FileAgentApplicationService, analyzed_items: Sequence[AnalyzedItem]
) -> None:
    """Approves genuine REVIEW decisions via the real approve_review() API
    only -- never fabricates approval, never touches PolicyDecision.decision
    (it stays REVIEW forever; see FA-012's authorization correction)."""
    for item in analyzed_items:
        if item.policy_outcome is PolicyOutcome.REVIEW:
            service.approve_review(item.policy_decision_id)


def _force_utf8_stdout() -> None:
    """Without this, Rich's box-drawing/em-dash characters render as
    replacement characters on some Windows shells (observed with
    git-bash's non-tty pipe) -- the inherited console codepage isn't
    UTF-8 by default. A raw legacy cmd.exe console without a UTF-8
    codepage (`chcp 65001`) may still show replacement glyphs -- a
    terminal limitation, not something this script can fully control."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the demo sandbox/appdata directory afterward for inspection",
    )
    parser.add_argument(
        "--approve-reviews",
        action="store_true",
        help="after the first preview, approve() genuine REVIEW items and "
        "rebuild the plan from the same policy_decision_ids",
    )
    parser.add_argument(
        "--lang",
        choices=("en", "es"),
        default="en",
        help="render section headings and reasons via the Spanish product-"
        "messaging presentation layer instead of raw technical facts "
        "(default: en, unchanged raw-fact rendering)",
    )
    args = parser.parse_args()

    # When stdout isn't a real terminal (e.g. piped/redirected), Rich falls
    # back to an 80-column default that truncates most columns below
    # readability -- widen it explicitly for that case only, so a genuine
    # narrow terminal is still respected when one is actually attached.
    console = Console() if sys.stdout.isatty() else Console(width=200)

    # This script owns DEMO_ROOT exclusively -- a fixed, hardcoded path
    # under the repo, never derived from user input. Removing it here (a
    # plain shutil.rmtree on our own scratch directory) is a developer-
    # utility concern, not a managed-root mutation; file_agent's own
    # production code gets no new generic recursive-delete primitive from
    # this script, and nothing under src/file_agent/ imports it.
    if DEMO_ROOT.exists():
        shutil.rmtree(DEMO_ROOT)
    sandbox_path = DEMO_ROOT / SANDBOX_DIRNAME
    sandbox_path.mkdir(parents=True)
    appdata_path = DEMO_ROOT / APPDATA_DIRNAME

    _seed_fixtures(sandbox_path)

    sandbox_root = SandboxRoot.from_path(sandbox_path)
    app_paths = AppPaths.from_root(appdata_path)
    service, engine = _build_service(sandbox_root, app_paths)

    try:
        before = _snapshot(sandbox_path)

        analysis = service.analyze_scan()
        policy_decision_ids: list[UUID] = [
            item.policy_decision_id for item in analysis.items
        ]
        plan = service.create_organization_plan(policy_decision_ids)

        after = _snapshot(sandbox_path)
        assert before == after, (
            "OrganizationPlan creation must never mutate a managed file, but "
            "the snapshot before/after analyze_scan()+create_organization_plan() "
            "differs"
        )

        render_plan(console, plan, sandbox_path, lang=args.lang)

        if args.approve_reviews:
            console.print()
            _approve_review_items(service, analysis.items)
            before_second = _snapshot(sandbox_path)
            # SAME policy_decision_ids -- a new snapshot of the same
            # lineage, never a "latest scan" re-derivation.
            second_plan = service.create_organization_plan(policy_decision_ids)
            after_second = _snapshot(sandbox_path)
            assert before_second == after_second, (
                "rebuilding the plan after approve_review() must never "
                "mutate a managed file"
            )
            render_plan(
                console,
                second_plan,
                sandbox_path,
                heading="FILEAGENT — ORGANIZATION PREVIEW (AFTER APPROVING REVIEWS)",
                lang=args.lang,
            )

        console.print()
        console.print("[bold]PREVIEW ONLY — no managed files were modified.[/bold]")
    finally:
        # Dispose before any cleanup attempt -- on Windows an undisposed
        # engine holds the sqlite file open, which would otherwise make
        # shutil.rmtree(DEMO_ROOT) below fail with PermissionError.
        engine.dispose()

    if args.keep:
        console.print(f"\nDemo sandbox kept at: {sandbox_path}")
        console.print(f"Demo app data kept at: {appdata_path}")
    else:
        shutil.rmtree(DEMO_ROOT)


if __name__ == "__main__":
    main()
