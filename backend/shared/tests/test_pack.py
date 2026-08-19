from __future__ import annotations

import pytest
from shared.pack import (
    ManifestError,
    PackManifest,
    PackState,
    compute_checksum,
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


def test_registry_metadata_parsed():
    manifest = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "display_name": "Billing",
            "developer": "AgentOS Labs",
            "homepage": "https://agentos.local/billing",
            "license": "Apache-2.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=1.0.0"}],
            "checksum": "abc123",
            "signature": "sig-abc123",
        }
    )
    assert manifest.developer == "AgentOS Labs"
    assert manifest.homepage == "https://agentos.local/billing"
    assert manifest.license == "Apache-2.0"
    assert manifest.dependency_names() == ["autoparts"]
    assert manifest.checksum == "abc123"
    assert manifest.signature == "sig-abc123"


def test_dependency_version_req_validated():
    with pytest.raises(ManifestError):
        parse_manifest(
            {
                "name": "x",
                "version": "1.0.0",
                "dependencies": [{"name": "y", "version_req": "latest"}],
            }
        )


def test_check_dependency():
    manifest = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=1.2.0"}],
        }
    )
    assert manifest.check_dependency("autoparts", "1.2.0") is True
    assert manifest.check_dependency("autoparts", "1.1.0") is False
    assert manifest.check_dependency("beauty", "0.0.1") is True  # no requirement


def test_compute_checksum_stable_and_deterministic():
    manifest = parse_manifest({"name": "x", "version": "1.0.0"})
    checksum = compute_checksum(manifest)
    assert checksum and len(checksum) == 64
    assert checksum == compute_checksum(manifest)
    # excluded fields do not change the checksum
    manifest2 = parse_manifest(
        {"name": "x", "version": "1.0.0", "checksum": "zzz", "signature": "yyy"}
    )
    assert compute_checksum(manifest2) == checksum
