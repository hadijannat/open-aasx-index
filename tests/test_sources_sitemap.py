"""Tests for the sitemap discovery source."""

from __future__ import annotations

import pytest
import respx

from harvest.sources.sitemap import (
    SitemapCandidate,
    SitemapSource,
    _is_potential_aasx_page,
    _parse_robots_txt,
    _parse_sitemap_xml,
    discover_sitemaps,
)


class TestParseRobotsTxt:
    """Tests for robots.txt parsing."""

    def test_extract_sitemap_urls(self) -> None:
        """Test extraction of sitemap URLs from robots.txt."""
        content = """
        User-agent: *
        Disallow: /private/

        Sitemap: https://example.com/sitemap.xml
        Sitemap: https://example.com/sitemap2.xml
        """
        sitemaps = _parse_robots_txt(content, "https://example.com")

        assert len(sitemaps) == 2
        assert "https://example.com/sitemap.xml" in sitemaps
        assert "https://example.com/sitemap2.xml" in sitemaps

    def test_case_insensitive(self) -> None:
        """Test case-insensitive parsing."""
        content = "SITEMAP: https://example.com/sitemap.xml"
        sitemaps = _parse_robots_txt(content, "https://example.com")

        assert len(sitemaps) == 1

    def test_relative_sitemap_url(self) -> None:
        """Test handling of relative sitemap URLs."""
        content = "Sitemap: /sitemap.xml"
        sitemaps = _parse_robots_txt(content, "https://example.com")

        assert sitemaps == ["https://example.com/sitemap.xml"]

    def test_no_sitemaps(self) -> None:
        """Test robots.txt with no sitemap entries."""
        content = "User-agent: *\nDisallow: /admin/"
        sitemaps = _parse_robots_txt(content, "https://example.com")

        assert sitemaps == []


class TestParseSitemapXml:
    """Tests for sitemap XML parsing."""

    def test_parse_regular_sitemap(self) -> None:
        """Test parsing a regular sitemap with page URLs."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>
        """
        pages, sitemaps = _parse_sitemap_xml(xml)

        assert len(pages) == 2
        assert "https://example.com/page1" in pages
        assert sitemaps == []

    def test_parse_sitemap_index(self) -> None:
        """Test parsing a sitemap index."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>
        """
        pages, sitemaps = _parse_sitemap_xml(xml)

        assert pages == []
        assert len(sitemaps) == 2

    def test_parse_without_namespace(self) -> None:
        """Test parsing sitemap without XML namespace."""
        xml = """<?xml version="1.0"?>
        <urlset>
            <url><loc>https://example.com/page</loc></url>
        </urlset>
        """
        pages, sitemaps = _parse_sitemap_xml(xml)

        assert len(pages) == 1

    def test_invalid_xml(self) -> None:
        """Test handling of invalid XML."""
        pages, sitemaps = _parse_sitemap_xml("not valid xml")

        assert pages == []
        assert sitemaps == []


class TestIsPotentialAasxPage:
    """Tests for AASX page detection."""

    def test_direct_aasx_file(self) -> None:
        """Test detection of direct AASX file URLs."""
        assert _is_potential_aasx_page("https://example.com/file.aasx") is True
        assert _is_potential_aasx_page("https://example.com/FILE.AASX") is True

    def test_keyword_detection(self) -> None:
        """Test detection via keywords."""
        assert _is_potential_aasx_page("https://example.com/aasx-samples") is True
        assert _is_potential_aasx_page("https://example.com/aas-files") is True
        assert _is_potential_aasx_page("https://example.com/digital-twin-demo") is True
        assert _is_potential_aasx_page("https://example.com/downloads") is True

    def test_non_matching_urls(self) -> None:
        """Test URLs that shouldn't match."""
        assert _is_potential_aasx_page("https://example.com/about") is False
        assert _is_potential_aasx_page("https://example.com/contact") is False


class TestSitemapCandidate:
    """Tests for SitemapCandidate dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        candidate = SitemapCandidate(
            url="https://example.com/test.aasx",
            source_ref="https://example.com/samples",
            filename="test.aasx",
        )
        d = candidate.to_dict()

        assert d["url"] == "https://example.com/test.aasx"
        assert d["source_type"] == "sitemap"
        assert d["source_ref"] == "https://example.com/samples"


class TestSitemapSource:
    """Tests for SitemapSource class."""

    @respx.mock
    def test_get_sitemap_from_robots(self) -> None:
        """Test getting sitemap URL from robots.txt."""
        respx.get("https://example.com/robots.txt").respond(
            200,
            text="Sitemap: https://example.com/sitemap.xml",
        )

        with SitemapSource() as source:
            sitemaps = source.get_sitemap_urls("https://example.com")

        assert sitemaps == ["https://example.com/sitemap.xml"]

    @respx.mock
    def test_fallback_to_common_locations(self) -> None:
        """Test fallback to common sitemap locations."""
        respx.get("https://example.com/robots.txt").respond(404)
        respx.get("https://example.com/sitemap.xml").respond(
            200,
            text='<?xml version="1.0"?><urlset></urlset>',
        )

        with SitemapSource() as source:
            sitemaps = source.get_sitemap_urls("https://example.com")

        assert sitemaps == ["https://example.com/sitemap.xml"]

    @respx.mock
    def test_crawl_sitemap(self) -> None:
        """Test crawling a sitemap for page URLs."""
        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/aasx-samples</loc></url>
            <url><loc>https://example.com/about</loc></url>
        </urlset>
        """
        respx.get("https://example.com/sitemap.xml").respond(200, text=sitemap_xml)

        with SitemapSource() as source:
            pages = source.crawl_sitemap("https://example.com/sitemap.xml")

        assert len(pages) == 2
        assert "https://example.com/aasx-samples" in pages

    @respx.mock
    def test_crawl_page_for_aasx(self) -> None:
        """Test crawling a page to find AASX links."""
        html = """
        <html>
        <body>
            <a href="https://example.com/file1.aasx">File 1</a>
            <a href="https://blocked.com/file2.aasx">File 2</a>
        </body>
        </html>
        """
        respx.get("https://example.com/samples").respond(200, text=html)

        with SitemapSource(allowed_domains={"example.com"}) as source:
            candidates = source.crawl_page_for_aasx("https://example.com/samples")

        assert len(candidates) == 1
        assert candidates[0].url == "https://example.com/file1.aasx"

    @respx.mock
    def test_direct_aasx_url_in_sitemap(self) -> None:
        """Test handling of direct AASX URLs in sitemap."""
        with SitemapSource(allowed_domains={"example.com"}) as source:
            candidates = source.crawl_page_for_aasx("https://example.com/sample.aasx")

        assert len(candidates) == 1
        assert candidates[0].url == "https://example.com/sample.aasx"

    @respx.mock
    def test_discover_site(self) -> None:
        """Test full site discovery."""
        respx.get("https://example.com/robots.txt").respond(
            200,
            text="Sitemap: https://example.com/sitemap.xml",
        )
        respx.get("https://example.com/sitemap.xml").respond(
            200,
            text="""<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.com/aasx-downloads</loc></url>
            </urlset>
            """,
        )
        respx.get("https://example.com/aasx-downloads").respond(
            200,
            text='<a href="https://example.com/test.aasx">Download</a>',
        )

        with SitemapSource(
            base_urls=["https://example.com"],
            allowed_domains={"example.com"},
        ) as source:
            candidates = source.discover()

        assert len(candidates) == 1
        assert candidates[0].url == "https://example.com/test.aasx"


class TestDiscoverSitemaps:
    """Tests for the convenience function."""

    @respx.mock
    def test_discover_sitemaps(self) -> None:
        """Test the discover_sitemaps convenience function."""
        respx.get("https://example.com/robots.txt").respond(404)
        respx.get("https://example.com/sitemap.xml").respond(
            200,
            text="""<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.com/sample.aasx</loc></url>
            </urlset>
            """,
        )

        candidates = discover_sitemaps(
            base_urls=["https://example.com"],
            allowed_domains={"example.com"},
        )

        assert len(candidates) >= 1
        assert candidates[0]["source_type"] == "sitemap"
