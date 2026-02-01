"""Common Crawl source for discovering AASX files via CDX API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from harvest.config import REQUEST_TIMEOUT_SECONDS, USER_AGENT
from harvest.rate_limiter import get_rate_limiter
from harvest.sources.seeds import _is_domain_allowed

logger = logging.getLogger(__name__)

# Common Crawl CDX API endpoint
CDX_API_URL = "https://index.commoncrawl.org/CC-MAIN-2024-10-index"


@dataclass
class CommonCrawlCandidate:
    """A candidate AASX file discovered via Common Crawl."""

    url: str
    source_ref: str = "commoncrawl"
    domain: str | None = None
    filename: str | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "url": self.url,
            "source_type": "commoncrawl",
            "source_ref": self.source_ref,
            "filename": self.filename,
        }


@dataclass
class CommonCrawlState:
    """State for incremental Common Crawl searching."""

    last_cursor: str | None = None
    discovered_domains: set[str] = field(default_factory=set)
    processed_urls: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "last_cursor": self.last_cursor,
            "discovered_domains": list(self.discovered_domains),
            "processed_urls": list(self.processed_urls),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommonCrawlState:
        """Create from dictionary."""
        return cls(
            last_cursor=data.get("last_cursor"),
            discovered_domains=set(data.get("discovered_domains", [])),
            processed_urls=set(data.get("processed_urls", [])),
        )


def _get_filename_from_url(url: str) -> str | None:
    """Extract filename from URL path."""
    parsed = urlparse(url)
    path = parsed.path
    if "/" in path:
        return path.rsplit("/", 1)[-1] or None
    return None


def _get_domain_from_url(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


class CommonCrawlSource:
    """Common Crawl CDX API source for discovering AASX files."""

    def __init__(
        self,
        allowed_domains: set[str] | None = None,
        cdx_url: str = CDX_API_URL,
        max_results: int = 50,
    ) -> None:
        """Initialize the Common Crawl source.

        Args:
            allowed_domains: Set of allowed domains for filtering
            cdx_url: CDX API URL to query
            max_results: Maximum results to return
        """
        self.allowed_domains = allowed_domains or set()
        self.cdx_url = cdx_url
        self.max_results = max_results
        self.rate_limiter = get_rate_limiter()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> CommonCrawlSource:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def query_cdx(
        self,
        url_pattern: str = "*.aasx",
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, str]], str | None]:
        """Query the Common Crawl CDX API.

        Args:
            url_pattern: URL pattern to search for
            limit: Maximum results per query
            cursor: Pagination cursor from previous query

        Returns:
            Tuple of (results, next_cursor)
        """
        self.rate_limiter.wait_sync("web")
        client = self._get_client()

        params: dict[str, Any] = {
            "url": url_pattern,
            "output": "json",
            "limit": limit,
            "matchType": "domain",  # Match at domain level
        }

        if cursor:
            params["cursor"] = cursor

        try:
            response = client.get(self.cdx_url, params=params)
            response.raise_for_status()

            # CDX API returns NDJSON (one JSON object per line)
            results = []
            lines = response.text.strip().split("\n")
            for line in lines:
                if line.strip():
                    try:
                        import json

                        record = json.loads(line)
                        results.append(record)
                    except Exception:
                        continue

            # Get next cursor from response headers if available
            next_cursor = response.headers.get("X-CDX-Next-Page-Token")

            return results, next_cursor

        except httpx.HTTPError as e:
            logger.warning(f"CDX API error: {e}")
            return [], None

    def search_aasx_urls(
        self,
        state: CommonCrawlState | None = None,
    ) -> tuple[list[CommonCrawlCandidate], CommonCrawlState]:
        """Search for AASX URLs in Common Crawl index.

        Args:
            state: Previous search state for incremental discovery

        Returns:
            Tuple of (candidates, updated_state)
        """
        if state is None:
            state = CommonCrawlState()

        candidates: list[CommonCrawlCandidate] = []
        new_domains: set[str] = set()

        # Query CDX for .aasx files
        results, next_cursor = self.query_cdx(
            url_pattern="*.aasx",
            limit=min(self.max_results * 2, 200),  # Get extra to filter
            cursor=state.last_cursor,
        )

        for record in results:
            url = record.get("url", "")

            # Skip already processed
            if url in state.processed_urls:
                continue

            # Check file extension
            if not url.lower().endswith(".aasx"):
                continue

            domain = _get_domain_from_url(url)

            # Track all discovered domains
            if domain not in state.discovered_domains:
                new_domains.add(domain)
                state.discovered_domains.add(domain)

            # Filter by allowed domains
            if self.allowed_domains and not _is_domain_allowed(url, self.allowed_domains):
                logger.debug(f"Skipping URL from non-allowed domain: {url}")
                continue

            candidates.append(
                CommonCrawlCandidate(
                    url=url,
                    domain=domain,
                    filename=_get_filename_from_url(url),
                    timestamp=record.get("timestamp"),
                )
            )
            state.processed_urls.add(url)

            if len(candidates) >= self.max_results:
                break

        # Log new domains for review
        if new_domains:
            logger.info(f"Discovered {len(new_domains)} new domains with AASX files:")
            for domain in sorted(new_domains)[:10]:
                logger.info(f"  - {domain}")

        # Update cursor for next run
        state.last_cursor = next_cursor

        return candidates, state

    def discover(
        self,
        state: CommonCrawlState | None = None,
    ) -> tuple[list[CommonCrawlCandidate], CommonCrawlState]:
        """Run discovery process.

        Args:
            state: Previous search state

        Returns:
            Tuple of (candidates, updated_state)
        """
        logger.info("Starting Common Crawl discovery")
        candidates, new_state = self.search_aasx_urls(state)
        logger.info(f"Common Crawl discovery found {len(candidates)} candidates")
        return candidates, new_state


def discover_commoncrawl(
    allowed_domains: set[str] | None = None,
    max_results: int = 50,
    state: CommonCrawlState | None = None,
) -> tuple[list[dict[str, Any]], CommonCrawlState]:
    """Convenience function for Common Crawl discovery.

    Args:
        allowed_domains: Set of allowed domains
        max_results: Maximum results to return
        state: Previous search state

    Returns:
        Tuple of (candidate_dicts, updated_state)
    """
    with CommonCrawlSource(
        allowed_domains=allowed_domains,
        max_results=max_results,
    ) as source:
        candidates, new_state = source.discover(state)
        return [c.to_dict() for c in candidates], new_state
