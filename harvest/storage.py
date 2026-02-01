"""Storage utilities for NDJSON catalog and state management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from harvest.config import CATALOG_NDJSON, STATE_FILE


@dataclass
class CatalogEntry:
    """A single entry in the AASX catalog."""

    id: str
    file: dict[str, Any]
    provenance: dict[str, Any]
    verification: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "file": self.file,
            "provenance": self.provenance,
            "verification": self.verification,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatalogEntry:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            file=data["file"],
            provenance=data["provenance"],
            verification=data["verification"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class HarvestState:
    """Persistent state for incremental harvesting."""

    # Cursors for pagination
    github_cursor: str | None = None
    commoncrawl_cursor: str | None = None

    # Sets of seen items (for deduplication)
    seen_urls: set[str] = field(default_factory=set)
    seen_sha256: set[str] = field(default_factory=set)

    # Timestamps
    last_run: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "github_cursor": self.github_cursor,
            "commoncrawl_cursor": self.commoncrawl_cursor,
            "seen_urls": list(self.seen_urls),
            "seen_sha256": list(self.seen_sha256),
            "last_run": self.last_run,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarvestState:
        """Create from dictionary."""
        return cls(
            github_cursor=data.get("github_cursor"),
            commoncrawl_cursor=data.get("commoncrawl_cursor"),
            seen_urls=set(data.get("seen_urls", [])),
            seen_sha256=set(data.get("seen_sha256", [])),
            last_run=data.get("last_run"),
        )

    def mark_run(self) -> None:
        """Update the last run timestamp."""
        self.last_run = datetime.now(timezone.utc).isoformat()


class CatalogStorage:
    """Read/write operations for the NDJSON catalog."""

    def __init__(self, path: Path = CATALOG_NDJSON) -> None:
        self.path = path

    def read_all(self) -> list[CatalogEntry]:
        """Read all entries from the catalog."""
        entries = []
        if not self.path.exists():
            return entries

        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    entries.append(CatalogEntry.from_dict(data))

        return entries

    def iter_entries(self) -> Iterator[CatalogEntry]:
        """Iterate over entries without loading all into memory."""
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    yield CatalogEntry.from_dict(data)

    def write_all(self, entries: list[CatalogEntry]) -> None:
        """Write all entries to the catalog (overwrites existing)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("w", encoding="utf-8") as f:
            for entry in entries:
                json.dump(entry.to_dict(), f, separators=(",", ":"))
                f.write("\n")

    def append(self, entry: CatalogEntry) -> None:
        """Append a single entry to the catalog."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("a", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, separators=(",", ":"))
            f.write("\n")

    def get_by_id(self, entry_id: str) -> CatalogEntry | None:
        """Find an entry by its ID."""
        for entry in self.iter_entries():
            if entry.id == entry_id:
                return entry
        return None

    def get_by_url(self, url: str) -> CatalogEntry | None:
        """Find an entry by its URL."""
        for entry in self.iter_entries():
            if entry.file.get("url") == url:
                return entry
        return None

    def get_by_sha256(self, sha256: str) -> CatalogEntry | None:
        """Find an entry by its SHA256 hash."""
        for entry in self.iter_entries():
            if entry.file.get("sha256") == sha256:
                return entry
        return None


class StateStorage:
    """Read/write operations for harvest state."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path

    def load(self) -> HarvestState:
        """Load state from file, or return empty state if not found."""
        if not self.path.exists():
            return HarvestState()

        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return HarvestState.from_dict(data)

    def save(self, state: HarvestState) -> None:
        """Save state to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)

    def update_from_catalog(self, state: HarvestState, catalog: CatalogStorage) -> None:
        """Update state's seen sets from catalog entries."""
        for entry in catalog.iter_entries():
            if url := entry.file.get("url"):
                state.seen_urls.add(url)
            if sha256 := entry.file.get("sha256"):
                state.seen_sha256.add(sha256)


def deduplicate_candidates(
    candidates: list[dict[str, Any]],
    state: HarvestState,
) -> list[dict[str, Any]]:
    """Filter out candidates that have already been processed.

    Args:
        candidates: List of candidate dicts with 'url' key
        state: Current harvest state with seen URLs

    Returns:
        List of new candidates not yet in the catalog
    """
    new_candidates = []
    for candidate in candidates:
        url = candidate.get("url")
        if url and url not in state.seen_urls:
            new_candidates.append(candidate)
    return new_candidates
