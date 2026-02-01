"""Tests for the GitHub discovery source."""

from __future__ import annotations

import respx

from harvest.sources.github import (
    GitHubCandidate,
    GitHubSearchState,
    GitHubSource,
    _blob_to_raw_url,
    _extract_repo_from_url,
    discover_github,
)


class TestBlobToRawUrl:
    """Tests for blob URL conversion."""

    def test_valid_blob_url(self) -> None:
        """Test conversion of valid blob URL."""
        blob = "https://github.com/owner/repo/blob/main/path/to/file.aasx"
        raw = _blob_to_raw_url(blob)
        assert raw == "https://raw.githubusercontent.com/owner/repo/main/path/to/file.aasx"

    def test_blob_url_with_branch(self) -> None:
        """Test conversion with different branch name."""
        blob = "https://github.com/org/project/blob/develop/samples/test.aasx"
        raw = _blob_to_raw_url(blob)
        assert raw == "https://raw.githubusercontent.com/org/project/develop/samples/test.aasx"

    def test_blob_url_with_commit_sha(self) -> None:
        """Test conversion with commit SHA."""
        blob = "https://github.com/owner/repo/blob/abc123def/file.aasx"
        raw = _blob_to_raw_url(blob)
        assert raw == "https://raw.githubusercontent.com/owner/repo/abc123def/file.aasx"

    def test_invalid_url(self) -> None:
        """Test that invalid URLs return None."""
        assert _blob_to_raw_url("https://example.com/file.aasx") is None
        assert _blob_to_raw_url("not a url") is None

    def test_non_blob_github_url(self) -> None:
        """Test that non-blob GitHub URLs return None."""
        assert _blob_to_raw_url("https://github.com/owner/repo") is None
        assert _blob_to_raw_url("https://github.com/owner/repo/tree/main") is None


class TestExtractRepoFromUrl:
    """Tests for repository extraction from URLs."""

    def test_valid_repo_url(self) -> None:
        """Test extraction from valid repo URL."""
        assert _extract_repo_from_url("https://github.com/owner/repo") == "owner/repo"

    def test_url_with_path(self) -> None:
        """Test extraction from URL with additional path."""
        assert (
            _extract_repo_from_url("https://github.com/org/project/blob/main/file.txt")
            == "org/project"
        )

    def test_invalid_url(self) -> None:
        """Test that invalid URLs return None."""
        assert _extract_repo_from_url("https://example.com/owner/repo") is None


class TestGitHubCandidate:
    """Tests for GitHubCandidate dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        candidate = GitHubCandidate(
            url="https://raw.githubusercontent.com/owner/repo/main/test.aasx",
            source_ref="owner/repo",
            license="MIT",
            filename="test.aasx",
        )
        d = candidate.to_dict()

        assert d["url"] == "https://raw.githubusercontent.com/owner/repo/main/test.aasx"
        assert d["source_type"] == "github"
        assert d["source_ref"] == "owner/repo"
        assert d["license"] == "MIT"
        assert d["filename"] == "test.aasx"

    def test_to_dict_minimal(self) -> None:
        """Test conversion with minimal fields."""
        candidate = GitHubCandidate(
            url="https://example.com/file.aasx",
            source_ref="owner/repo",
        )
        d = candidate.to_dict()

        assert d["url"] == "https://example.com/file.aasx"
        assert d["license"] is None


class TestGitHubSearchState:
    """Tests for GitHubSearchState."""

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = GitHubSearchState(
            code_search_page=5,
            topic_repos_seen={"owner/repo1", "owner/repo2"},
            repos_searched={"owner/repo1"},
        )
        d = state.to_dict()

        assert d["code_search_page"] == 5
        assert set(d["topic_repos_seen"]) == {"owner/repo1", "owner/repo2"}
        assert d["repos_searched"] == ["owner/repo1"]

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {
            "code_search_page": 3,
            "topic_repos_seen": ["repo1", "repo2"],
            "repos_searched": ["repo1"],
        }
        state = GitHubSearchState.from_dict(data)

        assert state.code_search_page == 3
        assert state.topic_repos_seen == {"repo1", "repo2"}
        assert state.repos_searched == {"repo1"}

    def test_from_empty_dict(self) -> None:
        """Test deserialization from empty dict."""
        state = GitHubSearchState.from_dict({})

        assert state.code_search_page == 1
        assert state.topic_repos_seen == set()


class TestGitHubSource:
    """Tests for GitHubSource class."""

    @respx.mock
    def test_search_code(self) -> None:
        """Test code search functionality."""
        respx.get("https://api.github.com/search/code").respond(
            200,
            json={
                "total_count": 2,
                "items": [
                    {
                        "name": "test1.aasx",
                        "html_url": "https://github.com/owner1/repo1/blob/main/test1.aasx",
                        "repository": {"full_name": "owner1/repo1"},
                    },
                    {
                        "name": "test2.aasx",
                        "html_url": "https://github.com/owner2/repo2/blob/main/dir/test2.aasx",
                        "repository": {"full_name": "owner2/repo2"},
                    },
                ],
            },
        )

        with GitHubSource() as source:
            candidates, has_more = source.search_code()

        assert len(candidates) == 2
        assert candidates[0].url == "https://raw.githubusercontent.com/owner1/repo1/main/test1.aasx"
        assert candidates[0].source_ref == "owner1/repo1"
        assert candidates[1].filename == "test2.aasx"
        assert has_more is False

    @respx.mock
    def test_search_code_pagination(self) -> None:
        """Test that pagination is detected correctly."""
        respx.get("https://api.github.com/search/code").respond(
            200,
            json={
                "total_count": 100,  # More than per_page
                "items": [
                    {
                        "name": "test.aasx",
                        "html_url": "https://github.com/owner/repo/blob/main/test.aasx",
                        "repository": {"full_name": "owner/repo"},
                    }
                ]
                * 30,
            },
        )

        with GitHubSource() as source:
            _, has_more = source.search_code(page=1, per_page=30)

        assert has_more is True

    @respx.mock
    def test_search_topics(self) -> None:
        """Test topic search functionality."""
        respx.get("https://api.github.com/search/repositories").respond(
            200,
            json={
                "items": [
                    {"full_name": "org/aasx-project"},
                    {"full_name": "user/digital-twin"},
                ]
            },
        )

        with GitHubSource() as source:
            repos = source.search_topics("aasx")

        assert repos == ["org/aasx-project", "user/digital-twin"]

    @respx.mock
    def test_search_repo_for_aasx(self) -> None:
        """Test searching a specific repo for AASX files."""
        # Mock code search
        respx.get("https://api.github.com/search/code").respond(
            200,
            json={
                "items": [
                    {
                        "name": "sample.aasx",
                        "html_url": "https://github.com/owner/repo/blob/main/samples/sample.aasx",
                    }
                ]
            },
        )
        # Mock license endpoint
        respx.get("https://api.github.com/repos/owner/repo/license").respond(
            200,
            json={"license": {"spdx_id": "Apache-2.0"}},
        )

        with GitHubSource() as source:
            candidates = source.search_repo_for_aasx("owner", "repo")

        assert len(candidates) == 1
        assert candidates[0].license == "Apache-2.0"
        assert candidates[0].source_ref == "owner/repo"

    @respx.mock
    def test_api_rate_limit_handling(self) -> None:
        """Test handling of rate limit response."""
        respx.get("https://api.github.com/search/code").respond(403)

        with GitHubSource() as source:
            candidates, has_more = source.search_code()

        assert candidates == []
        assert has_more is False

    @respx.mock
    def test_discover_incremental(self) -> None:
        """Test incremental discovery with state."""
        # Mock code search
        respx.get("https://api.github.com/search/code").respond(
            200,
            json={"total_count": 1, "items": []},
        )
        # Mock topic search
        respx.get("https://api.github.com/search/repositories").respond(
            200,
            json={"items": []},
        )

        state = GitHubSearchState(code_search_page=2)

        with GitHubSource(max_results=10) as source:
            _, new_state = source.discover(state)

        # State should be preserved
        assert new_state.code_search_page >= 2


class TestDiscoverGitHub:
    """Tests for the convenience function."""

    @respx.mock
    def test_discover_github(self) -> None:
        """Test the discover_github convenience function."""
        respx.get("https://api.github.com/search/code").respond(
            200,
            json={
                "total_count": 1,
                "items": [
                    {
                        "name": "test.aasx",
                        "html_url": "https://github.com/owner/repo/blob/main/test.aasx",
                        "repository": {"full_name": "owner/repo"},
                    }
                ],
            },
        )
        respx.get("https://api.github.com/search/repositories").respond(
            200,
            json={"items": []},
        )

        candidates, state = discover_github(max_results=10)

        assert len(candidates) >= 1
        assert candidates[0]["source_type"] == "github"
        assert isinstance(state, GitHubSearchState)
