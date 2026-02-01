"""Tests for the Common Crawl discovery source."""

from __future__ import annotations

import json

import respx

from harvest.sources.commoncrawl import (
    CommonCrawlCandidate,
    CommonCrawlSource,
    CommonCrawlState,
    _get_domain_from_url,
    _get_filename_from_url,
    discover_commoncrawl,
)


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_filename_from_url(self) -> None:
        """Test filename extraction."""
        assert _get_filename_from_url("https://example.com/path/file.aasx") == "file.aasx"
        assert _get_filename_from_url("https://example.com/file.aasx") == "file.aasx"
        assert _get_filename_from_url("https://example.com/") is None

    def test_get_domain_from_url(self) -> None:
        """Test domain extraction."""
        assert _get_domain_from_url("https://example.com/path") == "example.com"
        assert _get_domain_from_url("https://SUB.Example.COM/path") == "sub.example.com"
        assert _get_domain_from_url("http://example.com:8080/path") == "example.com:8080"


class TestCommonCrawlCandidate:
    """Tests for CommonCrawlCandidate dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        candidate = CommonCrawlCandidate(
            url="https://example.com/test.aasx",
            domain="example.com",
            filename="test.aasx",
            timestamp="20240101120000",
        )
        d = candidate.to_dict()

        assert d["url"] == "https://example.com/test.aasx"
        assert d["source_type"] == "commoncrawl"
        assert d["filename"] == "test.aasx"

    def test_to_dict_minimal(self) -> None:
        """Test conversion with minimal fields."""
        candidate = CommonCrawlCandidate(url="https://example.com/test.aasx")
        d = candidate.to_dict()

        assert d["url"] == "https://example.com/test.aasx"
        assert d["source_type"] == "commoncrawl"


class TestCommonCrawlState:
    """Tests for CommonCrawlState."""

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = CommonCrawlState(
            last_cursor="abc123",
            discovered_domains={"example.com", "test.org"},
            processed_urls={"https://example.com/file.aasx"},
        )
        d = state.to_dict()

        assert d["last_cursor"] == "abc123"
        assert set(d["discovered_domains"]) == {"example.com", "test.org"}
        assert d["processed_urls"] == ["https://example.com/file.aasx"]

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {
            "last_cursor": "xyz789",
            "discovered_domains": ["example.com"],
            "processed_urls": ["https://example.com/a.aasx"],
        }
        state = CommonCrawlState.from_dict(data)

        assert state.last_cursor == "xyz789"
        assert state.discovered_domains == {"example.com"}
        assert state.processed_urls == {"https://example.com/a.aasx"}

    def test_from_empty_dict(self) -> None:
        """Test deserialization from empty dict."""
        state = CommonCrawlState.from_dict({})

        assert state.last_cursor is None
        assert state.discovered_domains == set()
        assert state.processed_urls == set()


class TestCommonCrawlSource:
    """Tests for CommonCrawlSource class."""

    @respx.mock
    def test_query_cdx(self) -> None:
        """Test CDX API query."""
        cdx_response = "\n".join(
            [
                json.dumps({"url": "https://example.com/file1.aasx", "timestamp": "20240101"}),
                json.dumps({"url": "https://example.com/file2.aasx", "timestamp": "20240102"}),
            ]
        )
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        with CommonCrawlSource() as source:
            results, next_cursor = source.query_cdx("*.aasx")

        assert len(results) == 2
        assert results[0]["url"] == "https://example.com/file1.aasx"

    @respx.mock
    def test_query_cdx_error_handling(self) -> None:
        """Test handling of CDX API errors."""
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(500)

        with CommonCrawlSource() as source:
            results, next_cursor = source.query_cdx("*.aasx")

        assert results == []
        assert next_cursor is None

    @respx.mock
    def test_search_aasx_urls(self) -> None:
        """Test searching for AASX URLs."""
        cdx_response = "\n".join(
            [
                json.dumps({"url": "https://allowed.com/file.aasx", "timestamp": "20240101"}),
                json.dumps({"url": "https://blocked.com/file.aasx", "timestamp": "20240101"}),
            ]
        )
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        with CommonCrawlSource(allowed_domains={"allowed.com"}) as source:
            candidates, state = source.search_aasx_urls()

        assert len(candidates) == 1
        assert candidates[0].url == "https://allowed.com/file.aasx"
        # Both domains should be discovered
        assert "allowed.com" in state.discovered_domains
        assert "blocked.com" in state.discovered_domains

    @respx.mock
    def test_skip_processed_urls(self) -> None:
        """Test that already processed URLs are skipped."""
        cdx_response = json.dumps({"url": "https://example.com/file.aasx", "timestamp": "20240101"})
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        initial_state = CommonCrawlState(
            processed_urls={"https://example.com/file.aasx"}
        )

        with CommonCrawlSource(allowed_domains={"example.com"}) as source:
            candidates, state = source.search_aasx_urls(initial_state)

        assert len(candidates) == 0

    @respx.mock
    def test_filter_non_aasx_urls(self) -> None:
        """Test that non-AASX URLs are filtered."""
        cdx_response = "\n".join(
            [
                json.dumps({"url": "https://example.com/file.aasx"}),
                json.dumps({"url": "https://example.com/file.pdf"}),
                json.dumps({"url": "https://example.com/file.AASX"}),  # uppercase
            ]
        )
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        with CommonCrawlSource(allowed_domains={"example.com"}) as source:
            candidates, state = source.search_aasx_urls()

        # Should find both .aasx files (case insensitive)
        assert len(candidates) == 2

    @respx.mock
    def test_max_results_limit(self) -> None:
        """Test that max_results limit is respected."""
        cdx_response = "\n".join(
            [
                json.dumps({"url": f"https://example.com/file{i}.aasx"})
                for i in range(10)
            ]
        )
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        with CommonCrawlSource(allowed_domains={"example.com"}, max_results=3) as source:
            candidates, state = source.discover()

        assert len(candidates) == 3


class TestDiscoverCommoncrawl:
    """Tests for the convenience function."""

    @respx.mock
    def test_discover_commoncrawl(self) -> None:
        """Test the discover_commoncrawl convenience function."""
        cdx_response = json.dumps({"url": "https://example.com/test.aasx", "timestamp": "20240101"})
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
        )

        candidates, state = discover_commoncrawl(
            allowed_domains={"example.com"},
            max_results=10,
        )

        assert len(candidates) >= 1
        assert candidates[0]["source_type"] == "commoncrawl"
        assert isinstance(state, CommonCrawlState)

    @respx.mock
    def test_incremental_discovery(self) -> None:
        """Test incremental discovery with state."""
        cdx_response = json.dumps({"url": "https://example.com/new.aasx"})
        respx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index").respond(
            200,
            text=cdx_response,
            headers={"X-CDX-Next-Page-Token": "next_page_cursor"},
        )

        initial_state = CommonCrawlState(
            processed_urls={"https://example.com/old.aasx"}
        )

        candidates, new_state = discover_commoncrawl(
            allowed_domains={"example.com"},
            state=initial_state,
        )

        # New URL should be found
        assert len(candidates) == 1
        assert candidates[0]["url"] == "https://example.com/new.aasx"

        # Old URL should still be in processed_urls
        assert "https://example.com/old.aasx" in new_state.processed_urls
        assert "https://example.com/new.aasx" in new_state.processed_urls
