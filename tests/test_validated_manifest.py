"""ValidatedManifest: the type that makes the unchecked path unrepresentable.

The full "is validation actually enforced" story lives in
test_inspect.py, against validate_manifest_against_source. This file is
narrower: it proves the construction guard itself holds, across every
pydantic entry point that could otherwise be used to sneak around it.
"""

from __future__ import annotations

import json

import pytest
from cip.core.models import Manifest, ValidatedManifest
from pydantic import ValidationError


def _minimal_manifest_kwargs() -> dict[str, object]:
    return {
        "version": 1,
        "consultation": "test-consultation",
        "title": "Test",
        "source": "csv",
        "encoding": "utf-8",
        "columns": {},
        "questions": [],
    }


def test_direct_construction_via_init_fails():
    with pytest.raises(ValidationError, match="cannot be constructed directly"):
        ValidatedManifest(**_minimal_manifest_kwargs())


def test_direct_construction_via_model_validate_fails():
    """model_validate is a separate pydantic entry point from __init__ -
    guarding one and not the other would leave the door half shut.
    """
    with pytest.raises(ValidationError, match="cannot be constructed directly"):
        ValidatedManifest.model_validate(_minimal_manifest_kwargs())


def test_direct_construction_via_model_validate_json_fails():
    with pytest.raises(ValidationError, match="cannot be constructed directly"):
        ValidatedManifest.model_validate_json(json.dumps(_minimal_manifest_kwargs()))


def test_a_plain_manifest_is_unaffected_by_the_guard():
    """The guard belongs to ValidatedManifest alone - an ordinary
    Manifest, unresolved columns and all, must still construct freely.
    """
    manifest = Manifest.model_validate(_minimal_manifest_kwargs())
    assert manifest.consultation == "test-consultation"


def test_validated_manifest_is_a_manifest_subtype():
    """The parser boundary (parse_export(manifest: ValidatedManifest))
    relies on ordinary nominal subtyping to reject a plain Manifest: a
    ValidatedManifest must be usable anywhere a Manifest is accepted.
    """
    assert issubclass(ValidatedManifest, Manifest)
