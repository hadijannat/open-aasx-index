"""Sitemap source for discovering AASX files via sitemap.xml crawling."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from harvest.config import REQUEST_TIMEOUT_SECONDS, USER_AGENT
from harvest.rate_limiter import get_rate_limiter
from harvest.sources.seeds import _extract_aasx_links, _is_domain_allowed

logger = logging.getLogger(__name__)

# XML namespaces used in sitemaps
SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
}


@dataclass
class SitemapCandidate:
    """A candidate AASX file discovered via sitemap."""

    url: str
    source_ref: str  # The page URL where the link was found
    filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "url": self.url,
            "source_type": "sitemap",
            "source_ref": self.source_ref,
            "filename": self.filename,
        }


def _get_filename_from_url(url: str) -> str | None:
    """Extract filename from URL path."""
    parsed = urlparse(url)
    path = parsed.path
    if "/" in path:
        return path.rsplit("/", 1)[-1] or None
    return None


def _parse_robots_txt(content: str, base_url: str) -> list[str]:
    """Parse robots.txt to find sitemap URLs.

    Args:
        content: robots.txt content
        base_url: Base URL of the site

    Returns:
        List of sitemap URLs found
    """
    sitemaps = []
    for line in content.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sitemap_url = line.split(":", 1)[1].strip()
            # Handle relative URLs
            if not sitemap_url.startswith(("http://", "https://")):
                sitemap_url = urljoin(base_url, sitemap_url)
            sitemaps.append(sitemap_url)
    return sitemaps


def _parse_sitemap_xml(content: str) -> tuple[list[str], list[str]]:
    """Parse sitemap XML to extract URLs.

    Args:
        content: Sitemap XML content

    Returns:
        Tuple of (page_urls, nested_sitemap_urls)
    """
    page_urls = []
    sitemap_urls = []

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as e:
        logger.warning(f"Failed to parse sitemap XML: {e}")
        return [], []

    # Handle sitemap index (contains links to other sitemaps)
    for sitemap in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS):
        if sitemap.text:
            sitemap_urls.append(sitemap.text.strip())

    # Handle regular sitemap (contains page URLs)
    for url in root.findall(".//sm:url/sm:loc", SITEMAP_NS):
        if url.text:
            page_urls.append(url.text.strip())

    # Also try without namespace (some sitemaps don't use it)
    if not page_urls and not sitemap_urls:
        for sitemap in root.findall(".//sitemap/loc"):
            if sitemap.text:
                sitemap_urls.append(sitemap.text.strip())
        for url in root.findall(".//url/loc"):
            if url.text:
                page_urls.append(url.text.strip())

    return page_urls, sitemap_urls


def _is_potential_aasx_page(url: str) -> bool:
    """Check if a URL might contain AASX file links.

    Args:
        url: URL to check

    Returns:
        True if the URL looks like it might have AASX content
    """
    url_lower = url.lower()

    # Direct AASX file
    if url_lower.endswith(".aasx"):
        return True

    # Check the path only (not domain)
    parsed = urlparse(url_lower)
    path = parsed.path

    # Keywords that suggest AASX-related content
    keywords = [
        "aasx",
        "aas",
        "asset-administration",
        "digital-twin",
        "sample",
        "download",
    ]

    return any(kw in path for kw in keywords)


class SitemapSource:
    """Sitemap-based source for discovering AASX files."""

    def __init__(
        self,
        base_urls: list[str] | None = None,
        allowed_domains: set[str] | None = None,
        max_results: int = 50,
        max_pages_per_site: int = 20,
    ) -> None:
        """Initialize the sitemap source.

        Args:
            base_urls: List of site base URLs to crawl
            allowed_domains: Set of allowed domains for discovered links
            max_results: Maximum total results to return
            max_pages_per_site: Maximum pages to crawl per site
        """
        self.base_urls = base_urls or []
        self.allowed_domains = allowed_domains or set()
        self.max_results = max_results
        self.max_pages_per_site = max_pages_per_site
        self.rate_limiter = get_rate_limiter()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> SitemapSource:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _fetch(self, url: str) -> str | None:
        """Fetch content from a URL with rate limiting."""
        self.rate_limiter.wait_sync("web")
        client = self._get_client()

        try:
            response = client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None

    def get_sitemap_urls(self, base_url: str) -> list[str]:
        """Get sitemap URLs for a site.

        First checks robots.txt, then falls back to common locations.

        Args:
            base_url: Base URL of the site

        Returns:
            List of sitemap URLs
        """
        # Try robots.txt first
        robots_url = urljoin(base_url, "/robots.txt")
        robots_content = self._fetch(robots_url)

        if robots_content:
            sitemaps = _parse_robots_txt(robots_content, base_url)
            if sitemaps:
                return sitemaps

        # Fall back to common sitemap locations
        common_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/sitemap.xml"]
        for path in common_paths:
            sitemap_url = urljoin(base_url, path)
            content = self._fetch(sitemap_url)
            if content and ("<urlset" in content or "<sitemapindex" in content):
                return [sitemap_url]

        return []

    def crawl_sitemap(self, sitemap_url: str, depth: int = 0) -> list[str]:
        """Recursively crawl a sitemap to get page URLs.

        Args:
            sitemap_url: URL of the sitemap
            depth: Current recursion depth

        Returns:
            List of page URLs
        """
        if depth > 2:  # Limit recursion
            return []

        content = self._fetch(sitemap_url)
        if not content:
            return []

        page_urls, nested_sitemaps = _parse_sitemap_xml(content)

        # Recursively process nested sitemaps
        for nested in nested_sitemaps[:5]:  # Limit nested sitemaps
            page_urls.extend(self.crawl_sitemap(nested, depth + 1))

        return page_urls

    def crawl_page_for_aasx(self, page_url: str) -> list[SitemapCandidate]:
        """Crawl a page and extract AASX links.

        Args:
            page_url: URL of the page to crawl

        Returns:
            List of discovered candidates
        """
        # Check if URL itself is an AASX file
        if page_url.lower().endswith(".aasx"):
            if _is_domain_allowed(page_url, self.allowed_domains):
                return [
                    SitemapCandidate(
                        url=page_url,
                        source_ref=page_url,
                        filename=_get_filename_from_url(page_url),
                    )
                ]
            return []

        content = self._fetch(page_url)
        if not content:
            return []

        links = _extract_aasx_links(content, page_url)
        candidates = []

        for link in links:
            if _is_domain_allowed(link, self.allowed_domains):
                candidates.append(
                    SitemapCandidate(
                        url=link,
                        source_ref=page_url,
                        filename=_get_filename_from_url(link),
                    )
                )

        return candidates

    def discover_site(self, base_url: str) -> list[SitemapCandidate]:
        """Discover AASX files from a single site.

        Args:
            base_url: Base URL of the site

        Returns:
            List of discovered candidates
        """
        logger.info(f"Discovering from sitemap: {base_url}")

        sitemap_urls = self.get_sitemap_urls(base_url)
        if not sitemap_urls:
            logger.info(f"No sitemap found for {base_url}")
            return []

        # Get all page URLs from sitemaps
        all_pages = []
        for sitemap_url in sitemap_urls:
            pages = self.crawl_sitemap(sitemap_url)
            all_pages.extend(pages)

        # Filter to potentially relevant pages
        relevant_pages = [p for p in all_pages if _is_potential_aasx_page(p)]
        logger.info(f"Found {len(relevant_pages)} potentially relevant pages")

        # Crawl relevant pages
        candidates = []
        for page_url in relevant_pages[: self.max_pages_per_site]:
            page_candidates = self.crawl_page_for_aasx(page_url)
            candidates.extend(page_candidates)

        return candidates

    def discover(self) -> list[SitemapCandidate]:
        """Run discovery on all configured sites.

        Returns:
            List of discovered candidates
        """
        candidates: list[SitemapCandidate] = []

        for base_url in self.base_urls:
            if len(candidates) >= self.max_results:
                break

            site_candidates = self.discover_site(base_url)
            candidates.extend(site_candidates)

        logger.info(f"Sitemap discovery found {len(candidates)} total candidates")
        return candidates[: self.max_results]


def discover_sitemaps(
    base_urls: list[str],
    allowed_domains: set[str] | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Convenience function for sitemap discovery.

    Args:
        base_urls: List of site base URLs to crawl
        allowed_domains: Set of allowed domains
        max_results: Maximum results to return

    Returns:
        List of candidate dictionaries
    """
    with SitemapSource(
        base_urls=base_urls,
        allowed_domains=allowed_domains,
        max_results=max_results,
    ) as source:
        candidates = source.discover()
        return [c.to_dict() for c in candidates]
