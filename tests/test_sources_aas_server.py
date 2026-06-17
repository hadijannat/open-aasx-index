"""Tests for the live AAS server (instance) discovery source."""

from __future__ import annotations

import base64

import httpx
import respx

from harvest.sources.aas_server import (
    AasServerConfig,
    AasServerSource,
    _encode_id,
    _entry_id_for,
    _ref_last_value,
    discover_aas_servers,
    get_aas_server_configs,
)

BASE = "https://aas.example.com"
PREFIX = "/api/v3.0"


def _server() -> AasServerConfig:
    return AasServerConfig(base_url=BASE, name="Example", api_prefix=PREFIX)


def _shell(aas_id: str, id_short: str, submodel_ids: list[str]) -> dict:
    return {
        "id": aas_id,
        "idShort": id_short,
        "assetInformation": {"globalAssetId": f"{aas_id}/asset"},
        "submodels": [
            {"type": "ModelReference", "keys": [{"type": "Submodel", "value": sm}]}
            for sm in submodel_ids
        ],
    }


def _submodel(sm_id: str, semantic_id: str) -> dict:
    return {
        "id": sm_id,
        "semanticId": {"type": "ExternalReference", "keys": [{"value": semantic_id}]},
    }


def test_config_from_dict_and_endpoint() -> None:
    cfg = AasServerConfig.from_dict(
        {"url": "https://h.example/", "name": "H", "type": "registry", "api_prefix": "/api/v3.0/"}
    )
    assert cfg.base_url == "https://h.example"
    assert cfg.server_type == "registry"
    assert cfg.endpoint("/shells") == "https://h.example/api/v3.0/shells"


def test_get_aas_server_configs() -> None:
    config = {"aas_servers": [{"url": "https://a.example", "name": "A"}]}
    servers = get_aas_server_configs(config)
    assert len(servers) == 1
    assert servers[0].base_url == "https://a.example"


def test_encode_id_is_base64url_without_padding() -> None:
    encoded = _encode_id("https://acme.com/aas/1")
    assert "=" not in encoded
    decoded = base64.urlsafe_b64decode(encoded + "==").decode()
    assert decoded == "https://acme.com/aas/1"


def test_entry_id_is_stable_sha256() -> None:
    a = _entry_id_for("urn:x")
    b = _entry_id_for("urn:x")
    assert a == b
    assert a.startswith("sha256-") and len(a) == len("sha256-") + 64


def test_ref_last_value() -> None:
    assert _ref_last_value({"keys": [{"value": "a"}, {"value": "b"}]}) == "b"
    assert _ref_last_value({"keys": []}) is None
    assert _ref_last_value(None) is None


@respx.mock
def test_discover_enumerates_shells_with_semantic_ids() -> None:
    nameplate = "https://admin-shell.io/zvei/nameplate/1/0/Nameplate"
    respx.get(f"{BASE}{PREFIX}/shells").respond(
        200,
        json={
            "result": [_shell("urn:aas:1", "Pump", ["urn:sm:1"])],
            "paging_metadata": {},
        },
    )
    respx.get(f"{BASE}{PREFIX}/submodels").respond(
        200,
        json={"result": [_submodel("urn:sm:1", nameplate)], "paging_metadata": {}},
    )

    with AasServerSource([_server()], max_results=100) as source:
        entries = source.discover()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.provenance["source_type"] == "aas_server"
    assert entry.metadata["semantic_ids"] == [nameplate]
    assert entry.metadata["shells"][0]["id_short"] == "Pump"
    assert entry.file["url"] == f"{BASE}{PREFIX}/shells/{_encode_id('urn:aas:1')}"


@respx.mock
def test_registry_emits_shell_descriptor_urls() -> None:
    server = AasServerConfig(
        base_url=BASE, name="Registry", server_type="registry", api_prefix=PREFIX
    )
    respx.get(f"{BASE}{PREFIX}/shell-descriptors").respond(
        200, json={"result": [_shell("urn:aas:9", "Reg", [])], "paging_metadata": {}}
    )

    with AasServerSource([server], max_results=10) as source:
        entries = source.discover()

    assert len(entries) == 1
    assert entries[0].file["url"] == f"{BASE}{PREFIX}/shell-descriptors/{_encode_id('urn:aas:9')}"


@respx.mock
def test_pagination_follows_cursor() -> None:
    route = respx.get(f"{BASE}{PREFIX}/shells")
    route.side_effect = [
        # First page returns a cursor, second page ends pagination.
        httpx.Response(
            200,
            json={"result": [_shell("urn:aas:1", "A", [])], "paging_metadata": {"cursor": "C2"}},
        ),
        httpx.Response(
            200,
            json={"result": [_shell("urn:aas:2", "B", [])], "paging_metadata": {}},
        ),
    ]
    respx.get(f"{BASE}{PREFIX}/submodels").respond(200, json={"result": [], "paging_metadata": {}})

    with AasServerSource([_server()], max_results=100) as source:
        entries = source.discover()

    assert {e.metadata["shells"][0]["id"] for e in entries} == {"urn:aas:1", "urn:aas:2"}


@respx.mock
def test_unreachable_server_degrades_gracefully() -> None:
    respx.get(f"{BASE}{PREFIX}/shells").respond(503)
    entries = discover_aas_servers({"aas_servers": [{"url": BASE, "name": "Example"}]})
    assert entries == []


def test_no_servers_configured_returns_empty() -> None:
    assert discover_aas_servers({}) == []


@respx.mock
def test_max_results_caps_instances() -> None:
    shells = [_shell(f"urn:aas:{i}", f"S{i}", []) for i in range(5)]
    respx.get(f"{BASE}{PREFIX}/shells").respond(200, json={"result": shells, "paging_metadata": {}})
    respx.get(f"{BASE}{PREFIX}/submodels").respond(200, json={"result": [], "paging_metadata": {}})

    with AasServerSource([_server()], max_results=3) as source:
        entries = source.discover()

    assert len(entries) == 3
