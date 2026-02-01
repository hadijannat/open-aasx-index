"""Seed URL source for discovering AASX files from curated pages."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from harvest.config import REQUEST_TIMEOUT_SECONDS, SOURCES_FILE, USER_AGENT
from harvest.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)


@dataclass
class SeedCandidate:
    """A candidate AASX file discovered from a seed URL."""

    url: str
    source_ref: str  # The seed URL this was found on
    filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "url": self.url,
            "source_type": "seed",
            "source_ref": self.source_ref,
            "filename": self.filename,
        }


@dataclass
class SeedConfig:
    """Configuration for a seed source."""

    url: str
    name: str
    source_type: str = "seed"
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedConfig:
        """Create from dictionary."""
        return cls(
            url=data["url"],
            name=data.get("name", data["url"]),
            source_type=data.get("type", "seed"),
            notes=data.get("notes"),
        )


def load_sources_config(path: Path = SOURCES_FILE) -> dict[str, Any]:
    """Load the SOURCES.yml configuration file.

    Args:
        path: Path to the YAML file

    Returns:
        Parsed configuration dictionary
    """
    if not path.exists():
        logger.warning(f"Sources file not found: {path}")
        return {"sources": [], "allowed_domains": []}

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_seed_configs(config: dict[str, Any] | None = None) -> list[SeedConfig]:
    """Get seed configurations from SOURCES.yml.

    Args:
        config: Pre-loaded config dict, or None to load from file

    Returns:
        List of SeedConfig for seed-type sources
    """
    if config is None:
        config = load_sources_config()

    seeds = []
    for source in config.get("sources", []):
        if source.get("type") == "seed":
            seeds.append(SeedConfig.from_dict(source))

    return seeds


def get_allowed_domains(config: dict[str, Any] | None = None) -> set[str]:
    """Get the set of allowed domains from configuration.

    Args:
        config: Pre-loaded config dict, or None to load from file

    Returns:
        Set of allowed domain names
    """
    if config is None:
        config = load_sources_config()

    return set(config.get("allowed_domains", []))


def _is_domain_allowed(url: str, allowed_domains: set[str]) -> bool:
    """Check if a URL's domain is in the allowed list.

    Args:
        url: URL to check
        allowed_domains: Set of allowed domain names

    Returns:
        True if domain is allowed
    """
    if not allowed_domains:
        return True  # No restrictions if no domains specified

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Check exact match and subdomain match
    for allowed in allowed_domains:
        allowed = allowed.lower()
        if domain == allowed or domain.endswith(f".{allowed}"):
            return True

    return False


def _extract_aasx_links(html: str, base_url: str) -> list[str]:
    """Extract AASX file links from HTML content.

    Args:
        html: HTML content
        base_url: Base URL for resolving relative links

    Returns:
        List of absolute URLs to AASX files
    """
    # Find all href attributes that point to .aasx files
    # Pattern matches href="..." or href='...' with .aasx extension
    pattern = r'href=["\']([^"\']+\.aasx)["\']'

    links = set()
    for match in re.finditer(pattern, html, re.IGNORECASE):
        href = match.group(1)
        # Resolve relative URLs
        absolute_url = urljoin(base_url, href)
        links.add(absolute_url)

    return sorted(links)


def _get_filename_from_url(url: str) -> str | None:
    """Extract filename from URL path."""
    parsed = urlparse(url)
    path = parsed.path
    if "/" in path:
        return path.rsplit("/", 1)[-1] or None
    return None


class SeedSource:
    """Seed URL source for discovering AASX files."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        max_results: int = 50,
    ) -> None:
        self.config = config or load_sources_config()
        self.seeds = get_seed_configs(self.config)
        self.allowed_domains = get_allowed_domains(self.config)
        self.max_results = max_results
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

    def __enter__(self) -> SeedSource:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def fetch_page(self, url: str) -> str | None:
        """Fetch HTML content from a URL.

        Args:
            url: URL to fetch

        Returns:
            HTML content or None on error
        """
        self.rate_limiter.wait_sync("web")
        client = self._get_client()

        try:
            response = client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def crawl_seed(self, seed: SeedConfig) -> list[SeedCandidate]:
        """Crawl a seed URL and extract AASX links.

        Args:
            seed: Seed configuration

        Returns:
            List of discovered candidates
        """
        logger.info(f"Crawling seed: {seed.name} ({seed.url})")

        html = self.fetch_page(seed.url)
        if not html:
            return []

        links = _extract_aasx_links(html, seed.url)
        candidates = []

        for link in links:
            # Filter by allowed domains
            if not _is_domain_allowed(link, self.allowed_domains):
                logger.debug(f"Skipping link from non-allowed domain: {link}")
                continue

            candidates.append(
                SeedCandidate(
                    url=link,
                    source_ref=seed.url,
                    filename=_get_filename_from_url(link),
                )
            )

        logger.info(f"Found {len(candidates)} AASX links on {seed.name}")
        return candidates

    def discover(self) -> list[SeedCandidate]:
        """Run discovery on all seed URLs.

        Returns:
            List of discovered candidates
        """
        candidates: list[SeedCandidate] = []

        for seed in self.seeds:
            if len(candidates) >= self.max_results:
                break

            seed_candidates = self.crawl_seed(seed)
            candidates.extend(seed_candidates)

        logger.info(f"Seed discovery found {len(candidates)} total candidates")
        return candidates[: self.max_results]


def discover_seeds(
    config: dict[str, Any] | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Convenience function for seed discovery.

    Args:
        config: Optional pre-loaded configuration
        max_results: Maximum number of candidates

    Returns:
        List of candidate dictionaries
    """
    with SeedSource(config=config, max_results=max_results) as source:
        candidates = source.discover()
        return [c.to_dict() for c in candidates]
