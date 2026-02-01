"""Tests for the seed URL discovery source."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import respx
import yaml

from harvest.sources.seeds import (
    SeedCandidate,
    SeedConfig,
    SeedSource,
    _extract_aasx_links,
    _is_domain_allowed,
    discover_seeds,
    get_seed_configs,
    load_sources_config,
)


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_config() -> dict:
    """Sample configuration for testing."""
    return {
        "allowed_domains": ["example.com", "github.com"],
        "sources": [
            {
                "url": "https://example.com/aasx-samples",
                "name": "Example Samples",
                "type": "seed",
                "notes": "Test samples",
            },
            {
                "url": "https://github.com/org/repo",
                "name": "GitHub Repo",
                "type": "repo",  # Not a seed type
            },
        ],
    }


class TestExtractAasxLinks:
    """Tests for AASX link extraction from HTML."""

    def test_extract_quoted_links(self) -> None:
        """Test extraction of quoted href attributes."""
        html = """
        <a href="https://example.com/file1.aasx">File 1</a>
        <a href='https://example.com/file2.aasx'>File 2</a>
        """
        links = _extract_aasx_links(html, "https://base.com")

        assert len(links) == 2
        assert "https://example.com/file1.aasx" in links
        assert "https://example.com/file2.aasx" in links

    def test_extract_relative_links(self) -> None:
        """Test resolution of relative URLs."""
        html = '<a href="/samples/test.aasx">Test</a>'
        links = _extract_aasx_links(html, "https://example.com/page/")

        assert len(links) == 1
        assert links[0] == "https://example.com/samples/test.aasx"

    def test_extract_relative_path_links(self) -> None:
        """Test resolution of relative path URLs."""
        html = '<a href="./data/sample.aasx">Sample</a>'
        links = _extract_aasx_links(html, "https://example.com/docs/index.html")

        assert len(links) == 1
        assert "sample.aasx" in links[0]

    def test_case_insensitive(self) -> None:
        """Test case-insensitive matching."""
        html = '<a href="test.AASX">Test</a><a href="test.Aasx">Test2</a>'
        links = _extract_aasx_links(html, "https://example.com/")

        assert len(links) == 2

    def test_no_aasx_links(self) -> None:
        """Test HTML with no AASX links."""
        html = '<a href="file.pdf">PDF</a><a href="file.zip">ZIP</a>'
        links = _extract_aasx_links(html, "https://example.com/")

        assert links == []

    def test_deduplication(self) -> None:
        """Test that duplicate links are removed."""
        html = """
        <a href="same.aasx">Link 1</a>
        <a href="same.aasx">Link 2</a>
        """
        links = _extract_aasx_links(html, "https://example.com/")

        assert len(links) == 1


class TestIsDomainAllowed:
    """Tests for domain allowlist checking."""

    def test_exact_domain_match(self) -> None:
        """Test exact domain matching."""
        allowed = {"example.com", "test.org"}

        assert _is_domain_allowed("https://example.com/file.aasx", allowed) is True
        assert _is_domain_allowed("https://test.org/file.aasx", allowed) is True
        assert _is_domain_allowed("https://other.com/file.aasx", allowed) is False

    def test_subdomain_match(self) -> None:
        """Test subdomain matching."""
        allowed = {"example.com"}

        assert _is_domain_allowed("https://sub.example.com/file.aasx", allowed) is True
        assert _is_domain_allowed("https://deep.sub.example.com/file.aasx", allowed) is True

    def test_partial_match_rejected(self) -> None:
        """Test that partial domain matches are rejected."""
        allowed = {"example.com"}

        # 'notexample.com' should not match 'example.com'
        assert _is_domain_allowed("https://notexample.com/file.aasx", allowed) is False

    def test_empty_allowed_list(self) -> None:
        """Test that empty allowed list allows everything."""
        assert _is_domain_allowed("https://anything.com/file.aasx", set()) is True

    def test_case_insensitive(self) -> None:
        """Test case-insensitive domain matching."""
        allowed = {"Example.COM"}
        assert _is_domain_allowed("https://EXAMPLE.com/file.aasx", allowed) is True


class TestSeedConfig:
    """Tests for SeedConfig dataclass."""

    def test_from_dict_full(self) -> None:
        """Test creation with all fields."""
        data = {
            "url": "https://example.com/samples",
            "name": "Test Samples",
            "type": "seed",
            "notes": "Some notes",
        }
        config = SeedConfig.from_dict(data)

        assert config.url == "https://example.com/samples"
        assert config.name == "Test Samples"
        assert config.source_type == "seed"
        assert config.notes == "Some notes"

    def test_from_dict_minimal(self) -> None:
        """Test creation with minimal fields."""
        data = {"url": "https://example.com"}
        config = SeedConfig.from_dict(data)

        assert config.url == "https://example.com"
        assert config.name == "https://example.com"  # Falls back to URL
        assert config.source_type == "seed"


class TestSeedCandidate:
    """Tests for SeedCandidate dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        candidate = SeedCandidate(
            url="https://example.com/test.aasx",
            source_ref="https://example.com/samples",
            filename="test.aasx",
        )
        d = candidate.to_dict()

        assert d["url"] == "https://example.com/test.aasx"
        assert d["source_type"] == "seed"
        assert d["source_ref"] == "https://example.com/samples"
        assert d["filename"] == "test.aasx"


class TestLoadSourcesConfig:
    """Tests for configuration loading."""

    def test_load_valid_config(self, temp_dir: Path) -> None:
        """Test loading a valid configuration file."""
        config_path = temp_dir / "sources.yml"
        config_data = {"sources": [{"url": "https://example.com", "type": "seed"}]}
        config_path.write_text(yaml.dump(config_data))

        config = load_sources_config(config_path)

        assert len(config["sources"]) == 1

    def test_load_missing_file(self, temp_dir: Path) -> None:
        """Test loading when file doesn't exist."""
        config = load_sources_config(temp_dir / "nonexistent.yml")

        assert config == {"sources": [], "allowed_domains": []}


class TestGetSeedConfigs:
    """Tests for getting seed configurations."""

    def test_filters_by_type(self, sample_config: dict) -> None:
        """Test that only seed-type sources are returned."""
        seeds = get_seed_configs(sample_config)

        assert len(seeds) == 1
        assert seeds[0].name == "Example Samples"


class TestSeedSource:
    """Tests for SeedSource class."""

    @respx.mock
    def test_crawl_seed(self, sample_config: dict) -> None:
        """Test crawling a seed URL."""
        html = """
        <html>
        <body>
            <a href="https://example.com/sample1.aasx">Sample 1</a>
            <a href="https://example.com/sample2.aasx">Sample 2</a>
            <a href="https://blocked.com/blocked.aasx">Blocked</a>
        </body>
        </html>
        """
        respx.get("https://example.com/aasx-samples").respond(200, text=html)

        with SeedSource(config=sample_config) as source:
            seed_config = source.seeds[0]
            candidates = source.crawl_seed(seed_config)

        # Should find 2 candidates (blocked.com is filtered)
        assert len(candidates) == 2
        assert all(c.source_ref == "https://example.com/aasx-samples" for c in candidates)

    @respx.mock
    def test_fetch_error_handling(self, sample_config: dict) -> None:
        """Test handling of fetch errors."""
        respx.get("https://example.com/aasx-samples").respond(500)

        with SeedSource(config=sample_config) as source:
            seed_config = source.seeds[0]
            candidates = source.crawl_seed(seed_config)

        assert candidates == []

    @respx.mock
    def test_discover_all_seeds(self) -> None:
        """Test discovering from multiple seeds."""
        config = {
            "allowed_domains": ["site1.com", "site2.com"],
            "sources": [
                {"url": "https://site1.com/page", "name": "Site 1", "type": "seed"},
                {"url": "https://site2.com/page", "name": "Site 2", "type": "seed"},
            ],
        }

        respx.get("https://site1.com/page").respond(
            200,
            text='<a href="https://site1.com/a.aasx">A</a>',
        )
        respx.get("https://site2.com/page").respond(
            200,
            text='<a href="https://site2.com/b.aasx">B</a>',
        )

        with SeedSource(config=config) as source:
            candidates = source.discover()

        assert len(candidates) == 2


class TestDiscoverSeeds:
    """Tests for the convenience function."""

    @respx.mock
    def test_discover_seeds(self) -> None:
        """Test the discover_seeds convenience function."""
        config = {
            "allowed_domains": ["example.com"],
            "sources": [{"url": "https://example.com/samples", "name": "Test", "type": "seed"}],
        }

        respx.get("https://example.com/samples").respond(
            200,
            text='<a href="test.aasx">Test</a>',
        )

        candidates = discover_seeds(config=config)

        assert len(candidates) >= 1
        assert candidates[0]["source_type"] == "seed"
