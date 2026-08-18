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


def test_schema_has_exactly_the_declared_model_count() -> None:
    schema = build_schema()
    assert len(schema["$defs"]) == len(ALL_MODELS)
