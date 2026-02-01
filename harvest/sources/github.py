"""GitHub source for discovering AASX files via code search and topic search."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from harvest.config import REQUEST_TIMEOUT_SECONDS, USER_AGENT
from harvest.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

# GitHub API base URL
GITHUB_API = "https://api.github.com"

# Default topics to search for
DEFAULT_TOPICS = ["aasx", "aas", "asset-administration-shell"]


@dataclass
class GitHubCandidate:
    """A candidate AASX file discovered on GitHub."""

    url: str  # Raw download URL
    source_ref: str  # Repository reference (owner/repo)
    license: str | None = None
    filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "url": self.url,
            "source_type": "github",
            "source_ref": self.source_ref,
            "license": self.license,
            "filename": self.filename,
        }


@dataclass
class GitHubSearchState:
    """State for incremental GitHub searching."""

    code_search_page: int = 1
    topic_repos_seen: set[str] = field(default_factory=set)
    repos_searched: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "code_search_page": self.code_search_page,
            "topic_repos_seen": list(self.topic_repos_seen),
            "repos_searched": list(self.repos_searched),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubSearchState:
        """Create from dictionary."""
        return cls(
            code_search_page=data.get("code_search_page", 1),
            topic_repos_seen=set(data.get("topic_repos_seen", [])),
            repos_searched=set(data.get("repos_searched", [])),
        )


def _get_github_headers() -> dict[str, str]:
    """Get headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Add auth token if available
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _blob_to_raw_url(blob_url: str) -> str | None:
    """Convert a GitHub blob URL to a raw download URL.

    Example:
        https://github.com/owner/repo/blob/main/file.aasx
        -> https://raw.githubusercontent.com/owner/repo/main/file.aasx
    """
    # Parse the URL
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)",
        blob_url,
    )
    if not match:
        return None

    owner, repo, ref, path = match.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


def _extract_repo_from_url(url: str) -> str | None:
    """Extract owner/repo from a GitHub URL."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


class GitHubSource:
    """GitHub source for discovering AASX files."""

    def __init__(
        self,
        topics: list[str] | None = None,
        max_results: int = 100,
    ) -> None:
        self.topics = topics or DEFAULT_TOPICS
        self.max_results = max_results
        self.rate_limiter = get_rate_limiter()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                headers=_get_github_headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> GitHubSource:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _make_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a rate-limited request to the GitHub API."""
        self.rate_limiter.wait_sync("github")
        client = self._get_client()

        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                # Rate limited
                logger.warning("GitHub API rate limit hit")
            elif e.response.status_code == 422:
                # Invalid query
                logger.warning(f"GitHub API rejected query: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"GitHub API error: {e}")
            raise

    def _get_repo_license(self, owner: str, repo: str) -> str | None:
        """Fetch the license for a repository."""
        try:
            url = f"{GITHUB_API}/repos/{owner}/{repo}/license"
            data = self._make_request(url)
            license_info = data.get("license", {})
            spdx_id: str | None = license_info.get("spdx_id") if license_info else None
            return spdx_id
        except httpx.HTTPError:
            return None

    def search_code(
        self,
        extension: str = "aasx",
        page: int = 1,
        per_page: int = 30,
    ) -> tuple[list[GitHubCandidate], bool]:
        """Search GitHub code for files with the given extension.

        Args:
            extension: File extension to search for
            page: Page number (1-indexed)
            per_page: Results per page (max 100)

        Returns:
            Tuple of (candidates, has_more_pages)
        """
        query = f"extension:{extension}"
        url = f"{GITHUB_API}/search/code"
        params = {
            "q": query,
            "page": page,
            "per_page": min(per_page, 100),
        }

        try:
            data = self._make_request(url, params)
        except httpx.HTTPError:
            return [], False

        candidates = []
        items = data.get("items", [])

        for item in items:
            html_url = item.get("html_url", "")
            raw_url = _blob_to_raw_url(html_url)
            if not raw_url:
                continue

            repo_full_name = item.get("repository", {}).get("full_name", "")

            candidates.append(
                GitHubCandidate(
                    url=raw_url,
                    source_ref=repo_full_name,
                    filename=item.get("name"),
                )
            )

        # Check if there are more pages
        total_count = data.get("total_count", 0)
        has_more = (page * per_page) < total_count

        return candidates, has_more

    def search_topics(self, topic: str) -> list[str]:
        """Search for repositories with a given topic.

        Args:
            topic: Topic to search for

        Returns:
            List of repository full names (owner/repo)
        """
        url = f"{GITHUB_API}/search/repositories"
        params = {
            "q": f"topic:{topic}",
            "sort": "updated",
            "per_page": 30,
        }

        try:
            data = self._make_request(url, params)
        except httpx.HTTPError:
            return []

        repos = []
        for item in data.get("items", []):
            full_name = item.get("full_name")
            if full_name:
                repos.append(full_name)

        return repos

    def search_repo_for_aasx(
        self,
        owner: str,
        repo: str,
    ) -> list[GitHubCandidate]:
        """Search a specific repository for AASX files.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of candidates found
        """
        # Search for .aasx files in this specific repo
        query = f"extension:aasx repo:{owner}/{repo}"
        url = f"{GITHUB_API}/search/code"
        params = {"q": query, "per_page": 100}

        try:
            data = self._make_request(url, params)
        except httpx.HTTPError:
            return []

        candidates = []
        repo_license = self._get_repo_license(owner, repo)

        for item in data.get("items", []):
            html_url = item.get("html_url", "")
            raw_url = _blob_to_raw_url(html_url)
            if not raw_url:
                continue

            candidates.append(
                GitHubCandidate(
                    url=raw_url,
                    source_ref=f"{owner}/{repo}",
                    license=repo_license,
                    filename=item.get("name"),
                )
            )

        return candidates

    def discover(
        self,
        state: GitHubSearchState | None = None,
    ) -> tuple[list[GitHubCandidate], GitHubSearchState]:
        """Run full discovery process.

        Args:
            state: Previous search state for incremental discovery

        Returns:
            Tuple of (candidates, updated_state)
        """
        if state is None:
            state = GitHubSearchState()

        candidates: list[GitHubCandidate] = []

        # 1. Code search for .aasx files
        logger.info(f"Starting GitHub code search from page {state.code_search_page}")
        code_candidates, has_more = self.search_code(
            extension="aasx",
            page=state.code_search_page,
        )
        candidates.extend(code_candidates)

        if has_more:
            state.code_search_page += 1

        # 2. Topic search
        for topic in self.topics:
            if len(candidates) >= self.max_results:
                break

            logger.info(f"Searching repositories with topic: {topic}")
            repos = self.search_topics(topic)

            for repo_name in repos:
                if repo_name in state.repos_searched:
                    continue
                if len(candidates) >= self.max_results:
                    break

                state.topic_repos_seen.add(repo_name)

                # Search this repo for AASX files
                owner, repo = repo_name.split("/", 1)
                repo_candidates = self.search_repo_for_aasx(owner, repo)
                candidates.extend(repo_candidates)
                state.repos_searched.add(repo_name)

        logger.info(f"GitHub discovery found {len(candidates)} candidates")
        return candidates, state


def discover_github(
    max_results: int = 100,
    state: GitHubSearchState | None = None,
) -> tuple[list[dict[str, Any]], GitHubSearchState]:
    """Convenience function for GitHub discovery.

    Args:
        max_results: Maximum number of candidates to return
        state: Previous search state

    Returns:
        Tuple of (candidate_dicts, updated_state)
    """
    with GitHubSource(max_results=max_results) as source:
        candidates, new_state = source.discover(state)
        return [c.to_dict() for c in candidates], new_state
