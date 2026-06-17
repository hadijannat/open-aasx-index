"""Discover AAS *instances* (shells) from live AAS servers.

Unlike the file-based sources, which find downloadable ``.aasx`` packages, this
source talks to running Asset Administration Shell servers over the
standardized IDTA Part 2 HTTP/REST API ("Specification of the Asset
Administration Shell - Part 2: Application Programming Interfaces"). Each shell
hosted by a repository is one AAS *instance*, so this is the route to indexing
hundreds or thousands of instances rather than a handful of sample files.

Two endpoint kinds are supported:

* **repository** — an AAS Repository exposing ``GET {prefix}/shells`` (and
  ``GET {prefix}/submodels``). Most public demo servers are of this kind.
* **registry** — an AAS Registry exposing ``GET {prefix}/shell-descriptors``,
  which lists shells and where they are hosted.

The source paginates with the spec's ``cursor`` mechanism and fails safe: an
unreachable or non-compliant server logs a warning and contributes nothing
rather than aborting the run. Public demo servers are frequently offline, so
this resilience is essential.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from harvest.config import REQUEST_TIMEOUT_SECONDS, USER_AGENT
from harvest.rate_limiter import get_rate_limiter
from harvest.storage import CatalogEntry

logger = logging.getLogger(__name__)

DEFAULT_API_PREFIX = "/api/v3.0"
# Per-page size requested from servers (the spec caps this server-side anyway).
PAGE_SIZE = 100


@dataclass
class AasServerConfig:
    """Configuration for a single AAS server endpoint."""

    base_url: str
    name: str
    server_type: str = "repository"  # "repository" | "registry"
    api_prefix: str = DEFAULT_API_PREFIX

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AasServerConfig:
        """Create from a SOURCES.yml ``aas_servers`` entry."""
        return cls(
            base_url=data["url"].rstrip("/"),
            name=data.get("name", data["url"]),
            server_type=data.get("type", "repository"),
            api_prefix=data.get("api_prefix", DEFAULT_API_PREFIX).rstrip("/"),
        )

    def endpoint(self, path: str) -> str:
        """Build a full URL for an API path like ``/shells``."""
        return f"{self.base_url}{self.api_prefix}/{path.lstrip('/')}"


def get_aas_server_configs(config: dict[str, Any]) -> list[AasServerConfig]:
    """Extract AAS server configurations from a loaded SOURCES.yml dict."""
    return [AasServerConfig.from_dict(s) for s in config.get("aas_servers", [])]


def _encode_id(identifier: str) -> str:
    """Base64URL-encode an identifier for use in AAS API paths (spec §Identifiers)."""
    return base64.urlsafe_b64encode(identifier.encode("utf-8")).decode("ascii").rstrip("=")


def _entry_id_for(aas_id: str) -> str:
    """Derive a stable catalog id from an AAS identifier (no file to hash)."""
    digest = hashlib.sha256(aas_id.encode("utf-8")).hexdigest()
    return f"sha256-{digest}"


def _ref_last_value(reference: Any) -> str | None:
    """Return the value of the last key of an AAS Reference object."""
    if not isinstance(reference, dict):
        return None
    keys = reference.get("keys") or []
    if keys and isinstance(keys[-1], dict):
        value = keys[-1].get("value")
        return str(value) if value is not None else None
    return None


class AasServerSource:
    """Enumerate AAS instances from one or more live AAS servers."""

    def __init__(self, servers: list[AasServerConfig], max_results: int = 500) -> None:
        self.servers = servers
        self.max_results = max_results
        self.rate_limiter = get_rate_limiter()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> AasServerSource:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET a JSON object, returning None on any error."""
        self.rate_limiter.wait_sync("web")
        try:
            response = self._get_client().get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"AAS server request failed ({url}): {e}")
            return None

    def _paged(self, url: str, remaining: int) -> list[dict[str, Any]]:
        """Follow cursor pagination, collecting up to ``remaining`` result items."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None

        while len(items) < remaining:
            params: dict[str, Any] = {"limit": min(PAGE_SIZE, remaining - len(items))}
            if cursor:
                params["cursor"] = cursor

            data = self._get_json(url, params)
            if data is None:
                break

            page = data.get("result", [])
            if not isinstance(page, list) or not page:
                break
            valid_items = [p for p in page if isinstance(p, dict)]
            if not valid_items:
                # Non-empty page with no usable items: stop to avoid looping
                # forever when a malformed page also carries a cursor.
                break
            items.extend(valid_items)

            cursor = (data.get("paging_metadata") or {}).get("cursor")
            if not cursor:
                break

        return items[:remaining]

    def _submodel_semantic_ids(self, server: AasServerConfig, remaining: int) -> dict[str, str]:
        """Map submodel id -> its semantic id by enumerating the submodel repository."""
        mapping: dict[str, str] = {}
        if server.server_type != "repository":
            return mapping

        submodels = self._paged(server.endpoint("submodels"), remaining)
        for submodel in submodels:
            sm_id = submodel.get("id")
            sem_id = _ref_last_value(submodel.get("semanticId"))
            if sm_id and sem_id:
                mapping[str(sm_id)] = sem_id
        return mapping

    def _shell_to_entry(
        self,
        shell: dict[str, Any],
        server: AasServerConfig,
        semantic_by_submodel: dict[str, str],
    ) -> CatalogEntry | None:
        """Build a catalog entry from a shell JSON object."""
        aas_id = shell.get("id")
        if not aas_id:
            return None
        aas_id = str(aas_id)

        global_asset_id = None
        asset_info = shell.get("assetInformation")
        if isinstance(asset_info, dict):
            global_asset_id = asset_info.get("globalAssetId")

        # Resolve semantic ids from the shell's referenced submodels.
        semantic_ids: list[str] = []
        submodels_meta: list[dict[str, Any]] = []
        for ref in shell.get("submodels", []) or []:
            sm_id = _ref_last_value(ref)
            if not sm_id:
                continue
            sem_id = semantic_by_submodel.get(sm_id)
            sm_record: dict[str, Any] = {"id": sm_id}
            if sem_id:
                sm_record["semantic_id"] = sem_id
                semantic_ids.append(sem_id)
            submodels_meta.append(sm_record)

        metadata: dict[str, Any] = {
            "shells": [
                {
                    "id": aas_id,
                    **({"id_short": shell["idShort"]} if shell.get("idShort") else {}),
                    **({"global_asset_id": global_asset_id} if global_asset_id else {}),
                }
            ]
        }
        if submodels_meta:
            metadata["submodels"] = submodels_meta
        if semantic_ids:
            metadata["semantic_ids"] = sorted(set(semantic_ids))

        # Registries expose shells via /shell-descriptors; repositories via /shells.
        entry_path = "shell-descriptors" if server.server_type == "registry" else "shells"
        now = datetime.now(UTC).isoformat()
        return CatalogEntry(
            id=_entry_id_for(aas_id),
            file={"url": f"{server.endpoint(entry_path)}/{_encode_id(aas_id)}", "sha256": ""},
            provenance={
                "source_type": "aas_server",
                "source_ref": server.base_url,
                "license": None,
                "discovered_at": now,
                "last_verified_at": now,
            },
            verification={
                "status": "parseable",
                "summary": f"Live AAS instance served by {server.name}",
            },
            metadata=metadata,
        )

    def discover(self) -> list[CatalogEntry]:
        """Enumerate shells across all configured servers into catalog entries."""
        entries: list[CatalogEntry] = []
        seen_ids: set[str] = set()

        for server in self.servers:
            if len(entries) >= self.max_results:
                break

            remaining = self.max_results - len(entries)
            logger.info(f"Querying AAS server: {server.name} ({server.base_url})")

            shells_path = "shell-descriptors" if server.server_type == "registry" else "shells"
            shells = self._paged(server.endpoint(shells_path), remaining)
            if not shells:
                logger.info(f"  {server.name}: no shells (unreachable or empty)")
                continue

            semantic_by_submodel = self._submodel_semantic_ids(server, remaining)

            added = 0
            for shell in shells:
                entry = self._shell_to_entry(shell, server, semantic_by_submodel)
                if entry is None or entry.id in seen_ids:
                    continue
                seen_ids.add(entry.id)
                entries.append(entry)
                added += 1

            logger.info(f"  {server.name}: {added} instances")

        logger.info(f"AAS server discovery found {len(entries)} instances")
        return entries[: self.max_results]


def discover_aas_servers(
    config: dict[str, Any],
    max_results: int = 500,
) -> list[CatalogEntry]:
    """Convenience wrapper: discover AAS instances from servers in SOURCES.yml.

    Args:
        config: Loaded SOURCES.yml configuration.
        max_results: Maximum number of instances to collect across all servers.

    Returns:
        Ready-to-store catalog entries (already carry extracted metadata).
    """
    servers = get_aas_server_configs(config)
    if not servers:
        return []
    with AasServerSource(servers, max_results=max_results) as source:
        return source.discover()
