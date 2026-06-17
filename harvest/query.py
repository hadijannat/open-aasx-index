"""Query engine over the published AASX catalog.

This powers both the static HTTP query API (see :mod:`harvest.api`) and a small
command-line interface. It operates on plain catalog entry dictionaries (the
shape published in ``catalog.json``) so it can be used against either the local
catalog or a downloaded copy.

Each entry is *enriched* with template classification (current vs deprecated)
derived from its semantic IDs, enabling queries like "all files using current
IDTA submodel templates".
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harvest.config import CATALOG_JSON
from harvest.templates import (
    TemplateStatus,
    classify_semantic_ids,
    summarize_status,
)

Entry = dict[str, Any]


def enrich_entry(entry: Entry) -> Entry:
    """Return a copy of ``entry`` annotated with template classification.

    Adds ``metadata.templates`` (per semantic ID classification) and
    ``metadata.template_status`` (rolled-up current/deprecated/unknown).
    The original entry is not mutated.
    """
    enriched: Entry = json.loads(json.dumps(entry))  # cheap deep copy
    metadata = enriched.setdefault("metadata", {})
    semantic_ids = metadata.get("semantic_ids", []) or []

    matches = classify_semantic_ids(semantic_ids)
    metadata["templates"] = [m.to_dict() for m in matches]
    metadata["template_status"] = summarize_status(matches)
    return enriched


def enrich_entries(entries: list[Entry]) -> list[Entry]:
    """Enrich every entry with template classification."""
    return [enrich_entry(e) for e in entries]


@dataclass
class QueryFilters:
    """Filters for :func:`query_entries`. ``None`` means "no constraint"."""

    text: str | None = None
    status: str | None = None  # verification status
    source_type: str | None = None
    semantic_id: str | None = None  # substring match
    template_family: str | None = None
    template_status: TemplateStatus | None = None  # current/deprecated/unknown


def _matches_text(entry: Entry, needle: str) -> bool:
    needle = needle.lower()
    metadata = entry.get("metadata", {})
    haystacks: list[str] = [
        entry.get("id", ""),
        entry.get("file", {}).get("url", ""),
        entry.get("file", {}).get("filename", "") or "",
    ]
    for shell in metadata.get("shells", []):
        haystacks += [shell.get("id", ""), shell.get("id_short", "") or ""]
    for submodel in metadata.get("submodels", []):
        haystacks += [submodel.get("id", ""), submodel.get("id_short", "") or ""]
    haystacks += metadata.get("semantic_ids", []) or []
    return any(needle in h.lower() for h in haystacks if h)


def _matches(entry: Entry, filters: QueryFilters) -> bool:
    if filters.status and entry.get("verification", {}).get("status") != filters.status:
        return False
    if (
        filters.source_type
        and entry.get("provenance", {}).get("source_type") != filters.source_type
    ):
        return False
    if filters.semantic_id:
        sem_ids = entry.get("metadata", {}).get("semantic_ids", []) or []
        if not any(filters.semantic_id.lower() in s.lower() for s in sem_ids):
            return False
    if filters.template_status or filters.template_family:
        templates = entry.get("metadata", {}).get("templates", [])
        if filters.template_status and filters.template_status != entry.get(
            "metadata", {}
        ).get("template_status"):
            return False
        if filters.template_family and not any(
            t.get("family") == filters.template_family for t in templates
        ):
            return False
    return not (filters.text and not _matches_text(entry, filters.text))


def query_entries(
    entries: list[Entry],
    filters: QueryFilters | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
    enrich: bool = True,
) -> dict[str, Any]:
    """Filter and paginate catalog entries.

    Args:
        entries: Catalog entries (raw or already enriched).
        filters: Filtering constraints.
        limit: Maximum number of results to return (``None`` = all). Unlike the
            old hard-coded 50-row UI cap, this is explicit and optional.
        offset: Number of results to skip (for pagination).
        enrich: Whether to enrich entries with template classification first.

    Returns:
        A dict with ``count`` (matched total), ``offset``, ``limit`` and
        ``results`` (the requested page).
    """
    filters = filters or QueryFilters()
    pool = enrich_entries(entries) if enrich else entries

    matched = [e for e in pool if _matches(e, filters)]
    total = len(matched)

    page = matched[offset:]
    if limit is not None:
        page = page[:limit]

    return {
        "count": total,
        "offset": offset,
        "limit": limit,
        "results": page,
    }


def load_catalog(path: Path = CATALOG_JSON) -> list[Entry]:
    """Load catalog entries from a published ``catalog.json`` file."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("entries", [])


# ---------------------------------------------------------------------------
# Command-line interface: `python -m harvest.query ...`
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harvest.query",
        description="Query the Open AASX Index catalog (current vs deprecated aware)",
    )
    parser.add_argument("text", nargs="?", help="Free-text search term")
    parser.add_argument("--catalog", type=Path, default=CATALOG_JSON, help="Path to catalog.json")
    parser.add_argument("--status", help="Filter by verification status")
    parser.add_argument("--source", dest="source_type", help="Filter by source type")
    parser.add_argument("--semantic-id", help="Filter by semantic ID substring")
    parser.add_argument("--template-family", help="Filter by template family key")
    parser.add_argument(
        "--template-status",
        choices=["current", "deprecated", "unknown"],
        help="Filter by template currency",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max results (default: all)")
    parser.add_argument("--offset", type=int, default=0, help="Results to skip")
    parser.add_argument(
        "--count", action="store_true", help="Print only the number of matches"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ad-hoc catalog queries."""
    args = _build_parser().parse_args(argv)
    entries = load_catalog(args.catalog)

    filters = QueryFilters(
        text=args.text,
        status=args.status,
        source_type=args.source_type,
        semantic_id=args.semantic_id,
        template_family=args.template_family,
        template_status=args.template_status,
    )
    result = query_entries(entries, filters, limit=args.limit, offset=args.offset)

    if args.count:
        print(result["count"])
    else:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
