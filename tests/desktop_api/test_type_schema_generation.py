"""FA-017 type generation: the Pydantic -> JSON Schema step
(scripts/generate_desktop_view_schema.py) must keep producing a schema
entry for every View DTO and Params model it declares -- a drift guard so
a renamed/removed model is caught here rather than silently going stale in
packages/desktop-types/generated/index.ts."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_desktop_view_schema import ALL_MODELS, build_schema


def test_schema_has_an_entry_for_every_declared_model() -> None:
    schema = build_schema()
    defs = schema["$defs"]
    for model in ALL_MODELS:
        assert model.__name__ in defs, f"{model.__name__} missing from generated schema"


_SHARED_TYPE_DEFS = frozenset({"DestinationCategory"})
"""FA-017.2: DestinationCategory is a plain domain enum, not a View/Params
model in ALL_MODELS -- but once it's referenced as a field type by more
than one declared model (PlanAttentionView, DestinationSetupItemResultView,
DestinationSetupPrepareParams), Pydantic's schema generator legitimately
hoists it into its own shared $defs entry rather than inlining it
repeatedly. Named here explicitly so the count assertion below stays an
exact drift guard rather than silently loosening to `>=`."""


def test_schema_has_exactly_the_declared_model_count() -> None:
    schema = build_schema()
    defs = schema["$defs"]
    assert set(defs) - {m.__name__ for m in ALL_MODELS} == _SHARED_TYPE_DEFS
    assert len(defs) == len(ALL_MODELS) + len(_SHARED_TYPE_DEFS)
