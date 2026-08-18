#!/usr/bin/env python
"""FA-017 type-generation step 1 of 2: Pydantic View DTOs / request-param
models -> a single combined JSON Schema, written to
packages/desktop-types/schema/desktop-api.schema.json.

Step 2 (packages/desktop-types/scripts/build.mjs) converts that schema into
generated/index.ts via json-schema-to-typescript. Generated TypeScript is
checked in and compile-time only -- it does not runtime-validate anything
(see FA-017 design plan §"TYPE GENERATION").

Not part of the file_agent package -- a dev/tooling script only, matching
scripts/demo_preview.py's own established convention.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from file_agent.desktop_api import params as p
from file_agent.desktop_api import views as v

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = (
    REPO_ROOT / "packages" / "desktop-types" / "schema" / "desktop-api.schema.json"
)

VIEW_MODELS: tuple[type[BaseModel], ...] = (
    v.UserMessageView,
    v.ManagedRootView,
    v.ManagedRootListView,
    v.RemoveManagedRootResultView,
    v.ManagedRootUnavailableResultView,
    v.AnalyzedItemView,
    v.AnalysisFailureView,
    v.AnalysisResultView,
    v.PlanItemView,
    v.PlanSummaryView,
    v.PlanView,
    v.ReviewActionResultView,
    v.ApplyResultView,
    v.BatchApplyItemResultView,
    v.BatchApplySummaryView,
    v.BatchApplyResultView,
    v.BatchHistoryItemView,
    v.BatchHistoryEntryView,
    v.UnavailableBatchHistoryRowView,
    v.RecentHistoryView,
    v.HistoryLookupFailureView,
    v.UndoResultView,
    v.RestoreResultView,
)

PARAMS_MODELS: tuple[type[BaseModel], ...] = (
    p.ManagedRootsAddParams,
    p.ManagedRootsRemoveParams,
    p.ManagedRootsListParams,
    p.AnalysisRunParams,
    p.AnalysisReanalyzeFileParams,
    p.PlanCreateParams,
    p.ReviewActionParams,
    p.ApplyItemParams,
    p.ApplyItemsParams,
    p.HistoryGetBatchParams,
    p.HistoryListRecentParams,
    p.RecoveryUndoTransactionParams,
    p.RecoveryRestoreCaptureParams,
)

ALL_MODELS: tuple[type[BaseModel], ...] = VIEW_MODELS + PARAMS_MODELS


def build_schema() -> dict[str, object]:
    _, top_level_schema = models_json_schema(
        [(model, "serialization") for model in VIEW_MODELS]
        + [(model, "validation") for model in PARAMS_MODELS],
        ref_template="#/$defs/{model}",
    )
    return top_level_schema


def main() -> None:
    schema = build_schema()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
