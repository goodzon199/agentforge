"""Pack SDK: manifest format + validation for AgentOS packs.

A Pack is a vertical (autoparts, and any future one) deployed as its own
microservice. It ships a ``manifest.yaml`` describing what it provides; core
discovers, validates and registers it over the internal-HTTP contract without
code changes to core itself.

The SDK is intentionally pure (pydantic + yaml only, no SQLAlchemy) so both
core and every pack can import it.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

MANIFEST_FILENAME = "manifest.yaml"

# Lifecycle states a registered pack can be in. Tracked by core; the pack
# itself only exposes a manifest + health endpoint.
class PackState(str, Enum):
    installed = "installed"
    configured = "configured"
    active = "active"
    degraded = "degraded"
    disabled = "disabled"
    upgrade_required = "upgrade_required"


class PackAgent(BaseModel):
    """An agent the pack provides; ``type`` is the routing key used by core."""

    type: str
    display_name: str = ""


class PackWorkflow(BaseModel):
    """A named business process the pack ships (declared in 5.3, executed 5.3)."""

    name: str
    version: str = "1.0.0"


class PackDependency(BaseModel):
    """A dependency on another pack (sprint 5.7 registry)."""

    name: str = Field(min_length=1, max_length=80)
    version_req: str = ">=0.0.0"


class PackRoute(BaseModel):
    """An external API namespace a pack exposes through the core gateway.

    Sprint 5.8.1: the frontend knows a single core address; core routes
    ``/api/v1{prefix}/...`` to the pack's own service over the internal
    contract. ``prefix`` is the public namespace (e.g. ``/autoparts``),
    ``service`` is the registered pack name it routes to.
    """

    prefix: str = Field(pattern=r"^/[a-zA-Z0-9_-]+$")
    service: str = Field(min_length=1, max_length=80)


class PackManifest(BaseModel):
    """Validated contents of a pack's manifest.yaml.

    Sprint 5.7 adds registry metadata: the pack is a first-class artifact with
    developer, license, dependency requirements, a content checksum and an
    optional developer signature. Core never trusts a pack it cannot place in
    its registry with a stable identity.
    """

    name: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    display_name: str = ""
    description: str = ""

    # Registry metadata (sprint 5.7).
    developer: str = ""
    homepage: str = ""
    license: str = ""
    dependencies: list[PackDependency] = Field(default_factory=list)
    checksum: str = ""  # sha256 over the canonical manifest (developer-provided or verified)
    signature: str = ""  # optional developer signature over the checksum

    agents: list[PackAgent] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    workflows: list[PackWorkflow] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)

    # Sprint 5.8.1: API namespaces core exposes for this pack through the
    # platform gateway. Empty list means the pack ships no public API.
    routes: list[PackRoute] = Field(default_factory=list)

    required_core_version: str = ">=0.0.0"

    def agent_types(self) -> list[str]:
        return [a.type for a in self.agents]

    def workflow_names(self) -> list[str]:
        return [w.name for w in self.workflows]

    def dependency_names(self) -> list[str]:
        return [d.name for d in self.dependencies]

    def route_prefixes(self) -> list[str]:
        return [r.prefix for r in self.routes]

    def check_core_compatible(self, core_version: str) -> bool:
        """True when ``core_version`` satisfies ``required_core_version``."""
        return matches_requirement(core_version, self.required_core_version)

    def check_dependency(self, name: str, version: str) -> bool:
        """True when a registered dependency at ``version`` satisfies it."""
        for dep in self.dependencies:
            if dep.name == name:
                return matches_requirement(version, dep.version_req)
        return True  # no requirement on this pack


def compute_checksum(manifest: PackManifest) -> str:
    """sha256 over the canonical manifest JSON (without checksum/signature).

    Core verifies a pack's integrity before registering it; the pack may
    precompute the same value in its manifest.checksum.
    """
    import hashlib
    import json

    data = manifest.model_dump(mode="json", exclude={"checksum", "signature"})
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ManifestError(ValueError):
    """Raised when a manifest cannot be parsed or fails semantic validation."""


def parse_manifest(data: str | bytes | dict) -> PackManifest:
    """Parse and validate manifest content (YAML/JSON string or a dict)."""
    try:
        raw = yaml.safe_load(data) if isinstance(data, (str, bytes)) else data
    except yaml.YAMLError as exc:  # pragma: no cover - pydantic handles most
        raise ManifestError(f"manifest.yaml не валидный YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("manifest.yaml должен быть отображением (YAML map).")

    try:
        manifest = PackManifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"manifest.yaml не проходит схему: {exc}") from exc

    _validate_semantics(manifest)
    return manifest


def load_manifest(path: str | Path) -> PackManifest:
    """Load ``manifest.yaml`` from a pack directory."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ManifestError(f"manifest не найден: {file_path}")
    return parse_manifest(file_path.read_text(encoding="utf-8"))


def dump_manifest(manifest: PackManifest) -> str:
    """Serialize a manifest back to YAML (for tests/debug)."""
    return yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False)


def _validate_semantics(manifest: PackManifest) -> None:
    if manifest.required_core_version and not _is_requirement(manifest.required_core_version):
        raise ManifestError(
            f"required_core_version не в формате '<op><semver>': "
            f"{manifest.required_core_version!r}"
        )
    names = manifest.agent_types()
    if len(names) != len(set(names)):
        raise ManifestError("agents: имена агентов не уникальны.")
    prefixes = manifest.route_prefixes()
    if len(prefixes) != len(set(prefixes)):
        raise ManifestError("routes: префиксы не уникальны.")
    for route in manifest.routes:
        if route.service != manifest.name:
            raise ManifestError(
                f"routes: service {route.service!r} должен совпадать с именем "
                f"пака {manifest.name!r}."
            )
    for dep in manifest.dependencies:
        if not dep.version_req or not _is_requirement(dep.version_req):
            raise ManifestError(
                f"dependency {dep.name!r}: version_req не в формате '<op><semver>': "
                f"{dep.version_req!r}"
            )


# --- semver helpers ---------------------------------------------------------

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")
_REQ_RE = re.compile(r"^(>=|<=|==|!=|>|<)\s*(\d+\.\d+\.\d+)$")


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match(version.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups()[:3])  # type: ignore[return-value]


def _is_requirement(req: str) -> bool:
    return bool(_REQ_RE.match(req.strip()))


def _compare(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (left > right) - (left < right)


def matches_requirement(version: str, requirement: str) -> bool:
    """Semver match: e.g. matches_requirement("0.5.0", ">=0.5.0") -> True."""
    ver = _parse_semver(version)
    req = requirement.strip()
    match = _REQ_RE.match(req)
    if ver is None or match is None:
        return False
    op, target_str = match.group(1), match.group(2)
    target = _parse_semver(target_str)
    if target is None:
        return False
    cmp = _compare(ver, target)
    if op == ">=":
        return cmp >= 0
    if op == ">":
        return cmp > 0
    if op == "<=":
        return cmp <= 0
    if op == "<":
        return cmp < 0
    if op == "==":
        return cmp == 0
    if op == "!=":
        return cmp != 0
    return False
