"""Publish catalog artifacts to public directory."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from harvest.config import CATALOG_CSV, CATALOG_JSON, PUBLIC_DIR, STATS_JSON
from harvest.storage import CatalogStorage


def publish_catalog(
    catalog: CatalogStorage,
    output_dir: Path = PUBLIC_DIR,
) -> None:
    """Publish catalog to JSON, CSV, and stats files.

    Args:
        catalog: Catalog storage to read from
        output_dir: Directory to write output files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = catalog.read_all()

    # Sort entries by ID for stable output
    entries.sort(key=lambda e: e.id)

    # Publish JSON
    publish_json(entries, output_dir / "catalog.json")

    # Publish CSV
    publish_csv(entries, output_dir / "catalog.csv")

    # Publish stats
    publish_stats(entries, output_dir / "stats.json")


def publish_json(entries: list[Any], output_path: Path) -> None:
    """Publish catalog as formatted JSON array.

    Args:
        entries: List of catalog entries
        output_path: Path to write JSON file
    """
    data = [e.to_dict() for e in entries]

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def publish_csv(entries: list[Any], output_path: Path) -> None:
    """Publish catalog as CSV with key fields.

    Args:
        entries: List of catalog entries
        output_path: Path to write CSV file
    """
    fieldnames = [
        "id",
        "url",
        "size_bytes",
        "sha256",
        "source_type",
        "source_ref",
        "license",
        "status",
        "discovered_at",
        "last_verified_at",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for entry in entries:
            row = {
                "id": entry.id,
                "url": entry.file.get("url", ""),
                "size_bytes": entry.file.get("size_bytes", ""),
                "sha256": entry.file.get("sha256", ""),
                "source_type": entry.provenance.get("source_type", ""),
                "source_ref": entry.provenance.get("source_ref", ""),
                "license": entry.provenance.get("license", ""),
                "status": entry.verification.get("status", ""),
                "discovered_at": entry.provenance.get("discovered_at", ""),
                "last_verified_at": entry.provenance.get("last_verified_at", ""),
            }
            writer.writerow(row)


def publish_stats(entries: list[Any], output_path: Path) -> None:
    """Publish aggregate statistics as JSON.

    Args:
        entries: List of catalog entries
        output_path: Path to write stats JSON file
    """
    # Count by verification status
    status_counts: Counter[str] = Counter()
    for entry in entries:
        status = entry.verification.get("status", "unknown")
        status_counts[status] += 1

    # Count by source type
    source_counts: Counter[str] = Counter()
    for entry in entries:
        source = entry.provenance.get("source_type", "unknown")
        source_counts[source] += 1

    # Count semantic IDs
    semantic_id_counts: Counter[str] = Counter()
    for entry in entries:
        semantic_ids = entry.metadata.get("semantic_ids", [])
        for sem_id in semantic_ids:
            semantic_id_counts[sem_id] += 1

    # Build stats object
    stats = {
        "total_entries": len(entries),
        "by_status": dict(status_counts),
        "by_source": dict(source_counts),
        "top_semantic_ids": dict(semantic_id_counts.most_common(20)),
        "unique_semantic_ids": len(semantic_id_counts),
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)


def get_catalog_stats(catalog: CatalogStorage) -> dict[str, Any]:
    """Get statistics from the catalog without writing files.

    Args:
        catalog: Catalog storage to read from

    Returns:
        Statistics dictionary
    """
    entries = catalog.read_all()

    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for entry in entries:
        status_counts[entry.verification.get("status", "unknown")] += 1
        source_counts[entry.provenance.get("source_type", "unknown")] += 1

    return {
        "total": len(entries),
        "by_status": dict(status_counts),
        "by_source": dict(source_counts),
    }
