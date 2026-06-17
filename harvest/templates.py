"""Registry of IDTA Submodel Templates and deprecation classification.

Real-world AAS files reference *Submodel Templates* through ``semanticId``
references. The IDTA (Industrial Digital Twin Association) publishes these
templates and revises them over time, which means older versions get
**deprecated** and superseded by newer ones.

A catalog built only from old sample files therefore tends to contain mostly
*deprecated* template versions (e.g. Digital Nameplate 1.0/2.0) rather than the
*current* ones (3.0). This module gives the harvester the ability to tell the
two apart so consumers can "find all the new ones".

The registry below is a curated, best-effort list of the most common IDTA
templates. It is intentionally easy to extend: add a :class:`TemplateFamily`
and the classification logic does the rest. Within a family the declared
``current_version`` (and anything newer) is treated as *current*; lower
versions are *deprecated*. Semantic IDs that do not match any known family are
reported as *unknown* rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

TemplateStatus = Literal["current", "deprecated", "unknown"]

Version = tuple[int, ...]


@dataclass(frozen=True)
class TemplateFamily:
    """A family of related Submodel Template versions.

    Attributes:
        key: Stable machine-friendly identifier (e.g. ``digital-nameplate``).
        name: Human-readable name.
        idta: IDTA specification number, if known.
        pattern: Regex matched against a semantic ID. It MUST contain a
            ``ver`` named group capturing a slash/dot separated version
            (e.g. ``3/0`` or ``1.2``).
        current_version: The lowest version considered *current*. This version
            and anything newer is ``current``; lower versions are ``deprecated``.
        current_semantic_id: Canonical semantic ID of the current version,
            surfaced as ``superseded_by`` for deprecated matches.
    """

    key: str
    name: str
    pattern: str
    current_version: Version
    idta: str | None = None
    current_semantic_id: str | None = None
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_regex", re.compile(self.pattern, re.IGNORECASE))

    def match(self, semantic_id: str) -> Version | None:
        """Return the parsed version if ``semantic_id`` belongs to this family."""
        m = self._regex.search(semantic_id)
        if not m:
            return None
        return _parse_version(m.group("ver"))


def _parse_version(raw: str) -> Version:
    """Parse a ``1/2`` or ``1.2`` style version into a comparable tuple."""
    parts = re.split(r"[/.]", raw.strip())
    return tuple(int(p) for p in parts if p.isdigit())


# ---------------------------------------------------------------------------
# Curated registry of well-known IDTA Submodel Templates.
#
# NOTE: This is a best-effort, community-maintainable list. ``current_version``
# reflects the latest published revision known at authoring time; newer
# revisions found in the wild are still classified as ``current`` thanks to the
# ">=" comparison, so the registry fails safe.
# ---------------------------------------------------------------------------
TEMPLATE_FAMILIES: tuple[TemplateFamily, ...] = (
    TemplateFamily(
        key="digital-nameplate",
        name="Digital Nameplate",
        idta="IDTA 02006",
        pattern=r"admin-shell\.io/(?:zvei|idta)/nameplate/(?P<ver>\d+/\d+)/Nameplate",
        current_version=(3, 0),
        current_semantic_id="https://admin-shell.io/idta/nameplate/3/0/Nameplate",
    ),
    TemplateFamily(
        key="technical-data",
        name="Generic Frame for Technical Data",
        idta="IDTA 02003",
        pattern=r"admin-shell\.io/(?:zvei|idta)/TechnicalData/Submodel/(?P<ver>\d+/\d+)",
        current_version=(1, 2),
        current_semantic_id="https://admin-shell.io/idta/TechnicalData/Submodel/1/2",
    ),
    TemplateFamily(
        key="handover-documentation",
        name="Handover Documentation",
        idta="IDTA 02004",
        pattern=(
            r"admin-shell\.io/(?:vdi/2770|idta/HandoverDocumentation)"
            r"/(?P<ver>\d+/\d+)/(?:Documentation|Submodel)"
        ),
        current_version=(1, 2),
        current_semantic_id="https://admin-shell.io/idta/HandoverDocumentation/1/2/Submodel",
    ),
    TemplateFamily(
        key="hierarchical-structures",
        name="Hierarchical Structures enabling Bills of Material",
        idta="IDTA 02011",
        pattern=r"admin-shell\.io/idta/HierarchicalStructures/(?P<ver>\d+/\d+)/Submodel",
        current_version=(1, 1),
        current_semantic_id="https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel",
    ),
    TemplateFamily(
        key="time-series-data",
        name="Time Series Data",
        idta="IDTA 02008",
        pattern=r"admin-shell\.io/idta/TimeSeries/(?P<ver>\d+/\d+)/Submodel",
        current_version=(1, 1),
        current_semantic_id="https://admin-shell.io/idta/TimeSeries/1/1/Submodel",
    ),
    TemplateFamily(
        key="carbon-footprint",
        name="Carbon Footprint",
        idta="IDTA 02023",
        pattern=r"admin-shell\.io/idta/CarbonFootprint/(?P<ver>\d+/\d+)/Submodel",
        current_version=(1, 0),
        current_semantic_id="https://admin-shell.io/idta/CarbonFootprint/1/0/Submodel",
    ),
    TemplateFamily(
        key="asset-interfaces-description",
        name="Asset Interfaces Description",
        idta="IDTA 02017",
        pattern=r"admin-shell\.io/idta/AssetInterfacesDescription/(?P<ver>\d+/\d+)/Submodel",
        current_version=(1, 0),
        current_semantic_id="https://admin-shell.io/idta/AssetInterfacesDescription/1/0/Submodel",
    ),
)


@dataclass
class TemplateMatch:
    """Classification of a single semantic ID against the registry."""

    semantic_id: str
    status: TemplateStatus
    family_key: str | None = None
    family_name: str | None = None
    idta: str | None = None
    version: Version | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize for catalog/API output."""
        result: dict[str, object] = {
            "semantic_id": self.semantic_id,
            "status": self.status,
        }
        if self.family_key:
            result["family"] = self.family_key
        if self.family_name:
            result["name"] = self.family_name
        if self.idta:
            result["idta"] = self.idta
        if self.version is not None:
            result["version"] = ".".join(str(p) for p in self.version)
        if self.superseded_by:
            result["superseded_by"] = self.superseded_by
        return result


def classify_semantic_id(semantic_id: str) -> TemplateMatch:
    """Classify a semantic ID as current/deprecated/unknown.

    Args:
        semantic_id: A submodel ``semanticId`` reference value.

    Returns:
        A :class:`TemplateMatch` describing the template family and status.
    """
    for family in TEMPLATE_FAMILIES:
        version = family.match(semantic_id)
        if version is None:
            continue

        if version >= family.current_version:
            status: TemplateStatus = "current"
            superseded_by = None
        else:
            status = "deprecated"
            superseded_by = family.current_semantic_id

        return TemplateMatch(
            semantic_id=semantic_id,
            status=status,
            family_key=family.key,
            family_name=family.name,
            idta=family.idta,
            version=version,
            superseded_by=superseded_by,
        )

    return TemplateMatch(semantic_id=semantic_id, status="unknown")


def classify_semantic_ids(semantic_ids: list[str]) -> list[TemplateMatch]:
    """Classify a list of semantic IDs, preserving order and de-duplicating."""
    seen: set[str] = set()
    matches: list[TemplateMatch] = []
    for sem_id in semantic_ids:
        if sem_id in seen:
            continue
        seen.add(sem_id)
        matches.append(classify_semantic_id(sem_id))
    return matches


def summarize_status(matches: list[TemplateMatch]) -> TemplateStatus:
    """Roll up per-ID classifications into a single entry-level status.

    An entry is ``current`` if it has any current template and no deprecated
    ones, ``deprecated`` if it references any deprecated template, otherwise
    ``unknown``.
    """
    statuses = {m.status for m in matches}
    if "deprecated" in statuses:
        return "deprecated"
    if "current" in statuses:
        return "current"
    return "unknown"


def registry_to_dict() -> list[dict[str, object]]:
    """Export the registry as plain data for the public API."""
    return [
        {
            "key": fam.key,
            "name": fam.name,
            "idta": fam.idta,
            "current_version": ".".join(str(p) for p in fam.current_version),
            "current_semantic_id": fam.current_semantic_id,
        }
        for fam in TEMPLATE_FAMILIES
    ]
