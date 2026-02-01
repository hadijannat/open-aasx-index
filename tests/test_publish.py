"""Tests for the publish module."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from harvest.publish import (
    get_catalog_stats,
    publish_catalog,
    publish_csv,
    publish_json,
    publish_stats,
)
from harvest.storage import CatalogEntry, CatalogStorage


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_entries() -> list[CatalogEntry]:
    """Create sample catalog entries for testing."""
    return [
        CatalogEntry(
            id="sha256-aaa111",
            file={
                "url": "https://example.com/file1.aasx",
                "size_bytes": 1000,
                "sha256": "aaa111",
                "filename": "file1.aasx",
            },
            provenance={
                "source_type": "github",
                "source_ref": "owner/repo",
                "license": "MIT",
                "discovered_at": "2024-01-01T00:00:00Z",
                "last_verified_at": "2024-01-01T00:00:00Z",
            },
            verification={
                "status": "verified",
                "engine": "aas-test-engines/1.0",
                "exit_code": 0,
            },
            metadata={
                "shells": [{"id": "urn:shell:1", "id_short": "Shell1"}],
                "submodels": [{"id": "urn:sm:1", "semantic_id": "urn:sem:type1"}],
                "semantic_ids": ["urn:sem:type1"],
            },
        ),
        CatalogEntry(
            id="sha256-bbb222",
            file={
                "url": "https://example.com/file2.aasx",
                "size_bytes": 2000,
                "sha256": "bbb222",
            },
            provenance={
                "source_type": "seed",
                "source_ref": "https://example.com/samples",
                "discovered_at": "2024-01-02T00:00:00Z",
            },
            verification={
                "status": "parseable",
                "engine": "aas-test-engines/1.0",
                "exit_code": 1,
            },
            metadata={
                "semantic_ids": ["urn:sem:type1", "urn:sem:type2"],
            },
        ),
        CatalogEntry(
            id="sha256-ccc333",
            file={
                "url": "https://example.com/file3.aasx",
                "sha256": "ccc333",
            },
            provenance={
                "source_type": "github",
                "discovered_at": "2024-01-03T00:00:00Z",
            },
            verification={
                "status": "failed",
                "summary": "Download failed",
            },
        ),
    ]


class TestPublishJson:
    """Tests for JSON publishing."""

    def test_publish_json(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test publishing catalog as JSON."""
        output_path = temp_dir / "catalog.json"

        publish_json(sample_entries, output_path)

        assert output_path.exists()
        with output_path.open() as f:
            data = json.load(f)

        assert len(data) == 3
        assert data[0]["id"] == "sha256-aaa111"
        assert data[0]["file"]["url"] == "https://example.com/file1.aasx"

    def test_publish_json_sorted(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test that JSON output has sorted keys."""
        output_path = temp_dir / "catalog.json"

        publish_json(sample_entries, output_path)

        content = output_path.read_text()
        # Check that keys appear in alphabetical order in the first entry
        file_pos = content.find('"file"')
        id_pos = content.find('"id"')
        assert file_pos < id_pos  # 'file' should come before 'id' alphabetically


class TestPublishCsv:
    """Tests for CSV publishing."""

    def test_publish_csv(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test publishing catalog as CSV."""
        output_path = temp_dir / "catalog.csv"

        publish_csv(sample_entries, output_path)

        assert output_path.exists()
        with output_path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        assert rows[0]["id"] == "sha256-aaa111"
        assert rows[0]["url"] == "https://example.com/file1.aasx"
        assert rows[0]["status"] == "verified"
        assert rows[0]["source_type"] == "github"

    def test_csv_has_expected_columns(
        self, temp_dir: Path, sample_entries: list[CatalogEntry]
    ) -> None:
        """Test that CSV has expected column headers."""
        output_path = temp_dir / "catalog.csv"

        publish_csv(sample_entries, output_path)

        with output_path.open() as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

        expected = [
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
        assert fieldnames == expected

    def test_csv_handles_missing_fields(
        self, temp_dir: Path, sample_entries: list[CatalogEntry]
    ) -> None:
        """Test that CSV handles entries with missing optional fields."""
        output_path = temp_dir / "catalog.csv"

        publish_csv(sample_entries, output_path)

        with output_path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Third entry has minimal fields
        assert rows[2]["license"] == ""
        assert rows[2]["size_bytes"] == ""


class TestPublishStats:
    """Tests for stats publishing."""

    def test_publish_stats(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test publishing statistics."""
        output_path = temp_dir / "stats.json"

        publish_stats(sample_entries, output_path)

        assert output_path.exists()
        with output_path.open() as f:
            stats = json.load(f)

        assert stats["total_entries"] == 3

    def test_stats_by_status(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test status counts in stats."""
        output_path = temp_dir / "stats.json"

        publish_stats(sample_entries, output_path)

        with output_path.open() as f:
            stats = json.load(f)

        assert stats["by_status"]["verified"] == 1
        assert stats["by_status"]["parseable"] == 1
        assert stats["by_status"]["failed"] == 1

    def test_stats_by_source(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test source type counts in stats."""
        output_path = temp_dir / "stats.json"

        publish_stats(sample_entries, output_path)

        with output_path.open() as f:
            stats = json.load(f)

        assert stats["by_source"]["github"] == 2
        assert stats["by_source"]["seed"] == 1

    def test_stats_semantic_ids(self, temp_dir: Path, sample_entries: list[CatalogEntry]) -> None:
        """Test semantic ID statistics."""
        output_path = temp_dir / "stats.json"

        publish_stats(sample_entries, output_path)

        with output_path.open() as f:
            stats = json.load(f)

        # urn:sem:type1 appears in both entries with metadata
        assert stats["top_semantic_ids"]["urn:sem:type1"] == 2
        assert stats["top_semantic_ids"]["urn:sem:type2"] == 1
        assert stats["unique_semantic_ids"] == 2


class TestPublishCatalog:
    """Tests for the main publish_catalog function."""

    def test_publish_catalog_creates_all_files(
        self, temp_dir: Path, sample_entries: list[CatalogEntry]
    ) -> None:
        """Test that publish_catalog creates all output files."""
        # Create a catalog with sample entries
        catalog_path = temp_dir / "catalog.ndjson"
        catalog = CatalogStorage(catalog_path)
        catalog.write_all(sample_entries)

        output_dir = temp_dir / "public"
        publish_catalog(catalog, output_dir)

        assert (output_dir / "catalog.json").exists()
        assert (output_dir / "catalog.csv").exists()
        assert (output_dir / "stats.json").exists()

    def test_publish_catalog_creates_output_dir(
        self, temp_dir: Path, sample_entries: list[CatalogEntry]
    ) -> None:
        """Test that publish_catalog creates output directory if needed."""
        catalog_path = temp_dir / "catalog.ndjson"
        catalog = CatalogStorage(catalog_path)
        catalog.write_all(sample_entries)

        output_dir = temp_dir / "nested" / "public"
        publish_catalog(catalog, output_dir)

        assert output_dir.exists()


class TestGetCatalogStats:
    """Tests for the get_catalog_stats function."""

    def test_get_catalog_stats(
        self, temp_dir: Path, sample_entries: list[CatalogEntry]
    ) -> None:
        """Test getting stats without writing files."""
        catalog_path = temp_dir / "catalog.ndjson"
        catalog = CatalogStorage(catalog_path)
        catalog.write_all(sample_entries)

        stats = get_catalog_stats(catalog)

        assert stats["total"] == 3
        assert stats["by_status"]["verified"] == 1
        assert stats["by_source"]["github"] == 2

    def test_get_catalog_stats_empty(self, temp_dir: Path) -> None:
        """Test getting stats from empty catalog."""
        catalog_path = temp_dir / "catalog.ndjson"
        catalog = CatalogStorage(catalog_path)

        stats = get_catalog_stats(catalog)

        assert stats["total"] == 0
        assert stats["by_status"] == {}
