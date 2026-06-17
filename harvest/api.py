"""Publish a static HTTP query API under ``public/api/v1/``.

The Open AASX Index is hosted as a static site (GitHub Pages), so the "query
endpoint" is a set of pre-computed JSON documents at predictable URLs. External
tools can fetch them directly, e.g.::

    GET /api/v1/index.json                     # API descriptor + facet counts
    GET /api/v1/entries.json                   # all entries (template-enriched)
    GET /api/v1/templates.json                 # IDTA template registry + counts
    GET /api/v1/semantic-ids.json              # every semantic ID + classification
    GET /api/v1/by-status/{status}.json        # verified | parseable | failed
    GET /api/v1/by-source/{source}.json        # github | seed | sitemap | commoncrawl
    GET /api/v1/by-template-status/{s}.json    # current | deprecated | unknown

Every entry is enriched with template classification so consumers can find the
*current* (non-deprecated) AAS data instead of legacy sample files.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harvest.config import PUBLIC_DIR
from harvest.query import Entry, QueryFilters, enrich_entries, query_entries
from harvest.templates import TemplateStatus, classify_semantic_id, registry_to_dict

API_VERSION = "v1"

STATUS_VALUES = ("verified", "parseable", "failed")
SOURCE_VALUES = ("github", "seed", "sitemap", "commoncrawl", "aas_server")
FORMAT_VALUES = ("aasx", "json", "xml")
TEMPLATE_STATUS_VALUES: tuple[TemplateStatus, ...] = ("current", "deprecated", "unknown")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def build_semantic_id_index(entries: list[Entry]) -> list[dict[str, Any]]:
    """Aggregate semantic IDs across entries with classification and counts."""
    counts: Counter[str] = Counter()
    entry_ids: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        sem_ids = entry.get("metadata", {}).get("semantic_ids", []) or []
        for sem_id in set(sem_ids):
            counts[sem_id] += 1
            entry_ids[sem_id].append(entry["id"])

    index: list[dict[str, Any]] = []
    for sem_id, count in counts.most_common():
        record = classify_semantic_id(sem_id).to_dict()
        record["count"] = count
        record["entry_ids"] = sorted(entry_ids[sem_id])
        index.append(record)
    return index


def build_template_counts(entries: list[Entry]) -> dict[str, dict[str, int]]:
    """Count entries and semantic IDs per template family / currency."""
    family_status: dict[str, Counter[str]] = defaultdict(Counter)

    for entry in entries:
        for tmpl in entry.get("metadata", {}).get("templates", []):
            family = tmpl.get("family", "unknown")
            family_status[family][tmpl.get("status", "unknown")] += 1

    return {family: dict(statuses) for family, statuses in family_status.items()}


def publish_api(
    entries: list[Entry],
    output_dir: Path = PUBLIC_DIR,
    *,
    enrich: bool = True,
) -> None:
    """Generate the static query API into ``output_dir/api/<version>``.

    Args:
        entries: Raw catalog entries.
        output_dir: The public directory (the ``api/`` tree is created inside).
        enrich: Whether to enrich entries with template classification.
    """
    enriched = enrich_entries(entries) if enrich else entries
    api_dir = output_dir / "api" / API_VERSION

    generated_at = datetime.now(UTC).isoformat()

    # Facet counts
    status_counts: Counter[str] = Counter(
        e.get("verification", {}).get("status", "unknown") for e in enriched
    )
    source_counts: Counter[str] = Counter(
        e.get("provenance", {}).get("source_type", "unknown") for e in enriched
    )
    format_counts: Counter[str] = Counter(
        e.get("file", {}).get("format", "unknown") for e in enriched
    )
    template_status_counts: Counter[str] = Counter(
        e.get("metadata", {}).get("template_status", "unknown") for e in enriched
    )

    semantic_index = build_semantic_id_index(enriched)

    # /index.json -- descriptor consumers can read to discover the API
    descriptor = {
        "api_version": API_VERSION,
        "generated_at": generated_at,
        "total_entries": len(enriched),
        "facets": {
            "status": dict(status_counts),
            "source": dict(source_counts),
            "format": dict(format_counts),
            "template_status": dict(template_status_counts),
        },
        "unique_semantic_ids": len(semantic_index),
        "endpoints": {
            "entries": f"api/{API_VERSION}/entries.json",
            "templates": f"api/{API_VERSION}/templates.json",
            "semantic_ids": f"api/{API_VERSION}/semantic-ids.json",
            "by_status": f"api/{API_VERSION}/by-status/{{status}}.json",
            "by_source": f"api/{API_VERSION}/by-source/{{source}}.json",
            "by_format": f"api/{API_VERSION}/by-format/{{format}}.json",
            "by_template_status": f"api/{API_VERSION}/by-template-status/{{status}}.json",
        },
    }
    _write_json(api_dir / "index.json", descriptor)

    # /entries.json -- full enriched catalog
    _write_json(
        api_dir / "entries.json",
        {"count": len(enriched), "generated_at": generated_at, "results": enriched},
    )

    # /templates.json -- the registry plus how many catalog entries use each
    _write_json(
        api_dir / "templates.json",
        {
            "generated_at": generated_at,
            "registry": registry_to_dict(),
            "counts": build_template_counts(enriched),
        },
    )

    # /semantic-ids.json -- every semantic ID with classification + entry refs
    _write_json(
        api_dir / "semantic-ids.json",
        {
            "generated_at": generated_at,
            "count": len(semantic_index),
            "semantic_ids": semantic_index,
        },
    )

    # Pre-computed faceted result sets (already enriched, so skip re-enriching)
    for status in STATUS_VALUES:
        result = query_entries(enriched, QueryFilters(status=status), enrich=False)
        result["generated_at"] = generated_at
        _write_json(api_dir / "by-status" / f"{status}.json", result)

    for source in SOURCE_VALUES:
        result = query_entries(enriched, QueryFilters(source_type=source), enrich=False)
        result["generated_at"] = generated_at
        _write_json(api_dir / "by-source" / f"{source}.json", result)

    for fmt in FORMAT_VALUES:
        result = query_entries(enriched, QueryFilters(file_format=fmt), enrich=False)
        result["generated_at"] = generated_at
        _write_json(api_dir / "by-format" / f"{fmt}.json", result)

    for tstatus in TEMPLATE_STATUS_VALUES:
        result = query_entries(enriched, QueryFilters(template_status=tstatus), enrich=False)
        result["generated_at"] = generated_at
        _write_json(api_dir / "by-template-status" / f"{tstatus}.json", result)
