"""Tests for the catalog query engine."""

from __future__ import annotations

from typing import Any

from harvest.query import QueryFilters, enrich_entry, query_entries


def _entry(
    entry_id: str,
    *,
    status: str = "parseable",
    source: str = "seed",
    semantic_ids: list[str] | None = None,
    url: str = "https://example.com/file.aasx",
    file_format: str = "aasx",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "file": {"url": url, "filename": "file.aasx", "format": file_format},
        "provenance": {"source_type": source},
        "verification": {"status": status},
        "metadata": {"semantic_ids": semantic_ids or []},
    }


def _sample_entries() -> list[dict[str, Any]]:
    return [
        _entry(
            "sha256-1",
            status="verified",
            source="github",
            semantic_ids=["https://admin-shell.io/idta/nameplate/3/0/Nameplate"],
        ),
        _entry(
            "sha256-2",
            status="parseable",
            source="seed",
            semantic_ids=["https://admin-shell.io/zvei/nameplate/1/0/Nameplate"],
        ),
        _entry("sha256-3", status="failed", source="seed", semantic_ids=[]),
    ]


def test_enrich_entry_adds_template_status() -> None:
    enriched = enrich_entry(_sample_entries()[1])
    assert enriched["metadata"]["template_status"] == "deprecated"
    assert enriched["metadata"]["templates"][0]["status"] == "deprecated"


def test_enrich_entry_does_not_mutate_original() -> None:
    original = _sample_entries()[0]
    enrich_entry(original)
    assert "template_status" not in original["metadata"]


def test_filter_by_status() -> None:
    result = query_entries(_sample_entries(), QueryFilters(status="verified"))
    assert result["count"] == 1
    assert result["results"][0]["id"] == "sha256-1"


def test_filter_by_source() -> None:
    result = query_entries(_sample_entries(), QueryFilters(source_type="seed"))
    assert result["count"] == 2


def test_filter_by_format() -> None:
    entries = [
        _entry("sha256-1", file_format="aasx"),
        _entry("sha256-2", file_format="json"),
        _entry("sha256-3", file_format="xml"),
    ]
    assert query_entries(entries, QueryFilters(file_format="json"))["count"] == 1
    assert query_entries(entries, QueryFilters(file_format="aasx"))["count"] == 1


def test_filter_by_template_status_current() -> None:
    result = query_entries(_sample_entries(), QueryFilters(template_status="current"))
    assert result["count"] == 1
    assert result["results"][0]["id"] == "sha256-1"


def test_filter_by_template_status_deprecated() -> None:
    result = query_entries(_sample_entries(), QueryFilters(template_status="deprecated"))
    assert result["count"] == 1
    assert result["results"][0]["id"] == "sha256-2"


def test_filter_by_template_family() -> None:
    result = query_entries(_sample_entries(), QueryFilters(template_family="digital-nameplate"))
    assert result["count"] == 2


def test_filter_by_semantic_id_substring() -> None:
    result = query_entries(_sample_entries(), QueryFilters(semantic_id="nameplate/3/0"))
    assert result["count"] == 1


def test_text_search_matches_url() -> None:
    entries = [_entry("sha256-x", url="https://host/digital-twin.aasx")]
    assert query_entries(entries, QueryFilters(text="digital-twin"))["count"] == 1
    assert query_entries(entries, QueryFilters(text="nomatch"))["count"] == 0


def test_pagination_limit_and_offset() -> None:
    entries = [_entry(f"sha256-{i}") for i in range(10)]
    result = query_entries(entries, limit=3, offset=2)
    assert result["count"] == 10
    assert len(result["results"]) == 3
    assert result["results"][0]["id"] == "sha256-2"


def test_no_limit_returns_all() -> None:
    entries = [_entry(f"sha256-{i}") for i in range(60)]
    # Unlike the old hard-coded 50-row UI cap, all results come back.
    result = query_entries(entries)
    assert len(result["results"]) == 60
