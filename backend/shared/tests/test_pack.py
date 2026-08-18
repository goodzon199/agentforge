from __future__ import annotations

import pytest
from shared.pack import (
    ManifestError,
    PackManifest,
    PackState,
    matches_requirement,
    parse_manifest,
)


def test_parse_valid_manifest():
    manifest = parse_manifest(
        """
name: autoparts
version: 1.0.0
display_name: AutoParts
agents:
  - type: search
workflows:
  - name: sales_pipeline
permissions:
  - supplier.search
tools:
  - supplier_search
required_core_version: ">=0.5.0"
"""
    )
    assert isinstance(manifest, PackManifest)
    assert manifest.agent_types() == ["search"]
    assert manifest.workflow_names() == ["sales_pipeline"]


def test_parse_invalid_version():
    with pytest.raises(ManifestError):
        parse_manifest({"name": "x", "version": "not-semver"})


def test_parse_non_map():
    with pytest.raises(ManifestError):
        parse_manifest([1, 2, 3])


def test_duplicate_agents_rejected():
    with pytest.raises(ManifestError):
        parse_manifest(
            {
                "name": "x",
                "version": "1.0.0",
                "agents": [{"type": "a"}, {"type": "a"}],
            }
        )


def test_invalid_requirement_rejected():
    with pytest.raises(ManifestError):
        parse_manifest({"name": "x", "version": "1.0.0", "required_core_version": "lol"})


@pytest.mark.parametrize(
    ("version", "req", "expected"),
    [
        ("0.5.0", ">=0.5.0", True),
        ("0.5.1", ">=0.5.0", True),
        ("0.4.9", ">=0.5.0", False),
        ("0.5.0", ">0.5.0", False),
        ("0.6.0", ">0.5.0", True),
        ("0.5.0", "<=0.5.0", True),
        ("0.5.0", "<0.5.0", False),
        ("0.5.0", "==0.5.0", True),
        ("0.5.0", "!=0.5.0", False),
        ("1.0.0", ">=0.9.9", True),
    ],
)
def test_matches_requirement(version, req, expected):
    assert matches_requirement(version, req) is expected


def test_pack_state_values():
    values = {s.value for s in PackState}
    assert values == {
        "installed",
        "configured",
        "active",
        "degraded",
        "disabled",
        "upgrade_required",
    }
