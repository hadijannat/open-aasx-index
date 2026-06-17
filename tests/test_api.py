"""Tests for the static HTTP query API generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harvest.api import build_semantic_id_index, publish_api


def _entry(entry_id: str, status: str, source: str, semantic_ids: list[str]) -> dict[str, Any]:
    return {
        "id": entry_id,
        "file": {"url": f"https://example.com/{entry_id}.aasx"},
        "provenance": {"source_type": source},
        "verification": {"status": status},
        "metadata": {"semantic_ids": semantic_ids},
    }


def _entries() -> list[dict[str, Any]]:
    return [
        _entry(
            "sha256-a",
            "verified",
            "github",
            ["https://admin-shell.io/idta/nameplate/3/0/Nameplate"],
        ),
        _entry(
            "sha256-b",
            "parseable",
            "seed",
            ["https://admin-shell.io/zvei/nameplate/1/0/Nameplate"],
        ),
    ]


def _load(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def test_publish_api_writes_expected_files(tmp_path: Path) -> None:
    publish_api(_entries(), tmp_path)
    api = tmp_path / "api" / "v1"

    assert (api / "index.json").exists()
    assert (api / "entries.json").exists()
    assert (api / "templates.json").exists()
    assert (api / "semantic-ids.json").exists()
    assert (api / "by-status" / "verified.json").exists()
    assert (api / "by-source" / "github.json").exists()
    assert (api / "by-template-status" / "current.json").exists()
    assert (api / "by-template-status" / "deprecated.json").exists()


def test_index_facets(tmp_path: Path) -> None:
    publish_api(_entries(), tmp_path)
    index = _load(tmp_path / "api" / "v1" / "index.json")

    assert index["total_entries"] == 2
    assert index["facets"]["status"]["verified"] == 1
    assert index["facets"]["template_status"]["current"] == 1
    assert index["facets"]["template_status"]["deprecated"] == 1


def test_by_template_status_endpoint_filters(tmp_path: Path) -> None:
    publish_api(_entries(), tmp_path)
    current = _load(tmp_path / "api" / "v1" / "by-template-status" / "current.json")
    deprecated = _load(tmp_path / "api" / "v1" / "by-template-status" / "deprecated.json")

    assert current["count"] == 1
    assert current["results"][0]["id"] == "sha256-a"
    assert deprecated["count"] == 1
    assert deprecated["results"][0]["id"] == "sha256-b"


def test_entries_are_enriched(tmp_path: Path) -> None:
    publish_api(_entries(), tmp_path)
    entries = _load(tmp_path / "api" / "v1" / "entries.json")
    statuses = {e["id"]: e["metadata"]["template_status"] for e in entries["results"]}
    assert statuses == {"sha256-a": "current", "sha256-b": "deprecated"}


def test_semantic_id_index() -> None:
    index = build_semantic_id_index(_entries())
    by_id = {rec["semantic_id"]: rec for rec in index}
    assert by_id["https://admin-shell.io/idta/nameplate/3/0/Nameplate"]["status"] == "current"
    assert by_id["https://admin-shell.io/idta/nameplate/3/0/Nameplate"]["count"] == 1
    assert "sha256-a" in by_id["https://admin-shell.io/idta/nameplate/3/0/Nameplate"]["entry_ids"]


def test_templates_json_counts(tmp_path: Path) -> None:
    publish_api(_entries(), tmp_path)
    templates = _load(tmp_path / "api" / "v1" / "templates.json")
    assert any(fam["key"] == "digital-nameplate" for fam in templates["registry"])
    counts = templates["counts"]["digital-nameplate"]
    assert counts.get("current") == 1
    assert counts.get("deprecated") == 1
