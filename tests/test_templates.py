"""Tests for the IDTA submodel template registry and classification."""

from __future__ import annotations

from harvest.templates import (
    classify_semantic_id,
    classify_semantic_ids,
    registry_to_dict,
    summarize_status,
)


def test_deprecated_nameplate_versions_are_flagged() -> None:
    for sem_id in (
        "https://admin-shell.io/zvei/nameplate/1/0/Nameplate",
        "https://admin-shell.io/zvei/nameplate/2/0/Nameplate",
    ):
        match = classify_semantic_id(sem_id)
        assert match.status == "deprecated"
        assert match.family_key == "digital-nameplate"
        assert match.superseded_by == "https://admin-shell.io/idta/nameplate/3/0/Nameplate"


def test_current_nameplate_is_current() -> None:
    match = classify_semantic_id("https://admin-shell.io/idta/nameplate/3/0/Nameplate")
    assert match.status == "current"
    assert match.superseded_by is None
    assert match.version == (3, 0)


def test_newer_than_registry_still_current() -> None:
    # A future revision should fail safe to "current", not "deprecated".
    match = classify_semantic_id("https://admin-shell.io/idta/nameplate/4/0/Nameplate")
    assert match.status == "current"


def test_technical_data_versions() -> None:
    old = classify_semantic_id("https://admin-shell.io/ZVEI/TechnicalData/Submodel/1/1")
    assert old.status == "deprecated"
    assert old.family_key == "technical-data"

    new = classify_semantic_id("https://admin-shell.io/idta/TechnicalData/Submodel/1/2")
    assert new.status == "current"


def test_handover_documentation_vdi_and_idta() -> None:
    vdi = classify_semantic_id("https://admin-shell.io/vdi/2770/1/0/Documentation")
    assert vdi.family_key == "handover-documentation"
    assert vdi.status == "deprecated"


def test_unknown_semantic_id() -> None:
    match = classify_semantic_id("0173-1#01-AHF578#001")
    assert match.status == "unknown"
    assert match.family_key is None
    assert match.to_dict() == {"semantic_id": "0173-1#01-AHF578#001", "status": "unknown"}


def test_classify_list_dedupes_and_preserves_order() -> None:
    ids = [
        "https://admin-shell.io/idta/nameplate/3/0/Nameplate",
        "https://admin-shell.io/zvei/nameplate/1/0/Nameplate",
        "https://admin-shell.io/idta/nameplate/3/0/Nameplate",  # duplicate
    ]
    matches = classify_semantic_ids(ids)
    assert len(matches) == 2
    assert matches[0].status == "current"
    assert matches[1].status == "deprecated"


def test_summarize_status_prefers_deprecated() -> None:
    matches = classify_semantic_ids(
        [
            "https://admin-shell.io/idta/nameplate/3/0/Nameplate",
            "https://admin-shell.io/zvei/nameplate/1/0/Nameplate",
        ]
    )
    assert summarize_status(matches) == "deprecated"


def test_summarize_status_current_only() -> None:
    matches = classify_semantic_ids(["https://admin-shell.io/idta/nameplate/3/0/Nameplate"])
    assert summarize_status(matches) == "current"


def test_summarize_status_unknown_when_empty() -> None:
    assert summarize_status([]) == "unknown"


def test_registry_export_shape() -> None:
    registry = registry_to_dict()
    assert registry, "registry should not be empty"
    keys = {fam["key"] for fam in registry}
    assert "digital-nameplate" in keys
    for fam in registry:
        assert {"key", "name", "current_version"} <= set(fam)
