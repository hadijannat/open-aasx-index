"""Tests for AAS format detection and content sniffing."""

from __future__ import annotations

import json
from pathlib import Path

from harvest.formats import (
    AAS_FILE_EXTENSIONS,
    detect_format,
    is_probably_aas_file,
    looks_like_aas_json,
    looks_like_aas_xml,
)
from harvest.sources.seeds import _extract_aas_links, _extract_aasx_links


def test_detect_format() -> None:
    assert detect_format("model.aasx") == "aasx"
    assert detect_format("Environment.JSON") == "json"
    assert detect_format("https://h/x/env.xml") == "xml"
    assert detect_format("notes.txt") is None


def test_detect_format_with_query_and_fragment() -> None:
    assert detect_format("https://h/env.xml?download=1") == "xml"
    assert detect_format("https://h/env.json#raw") == "json"
    assert detect_format("https://h/model.aasx?token=abc#frag") == "aasx"


def test_extract_aas_links_keeps_query_suffix() -> None:
    html = '<a href="https://h/env.json?download=1">x</a>'
    assert _extract_aas_links(html, "https://h/") == ["https://h/env.json?download=1"]


def test_extensions_constant() -> None:
    assert AAS_FILE_EXTENSIONS == (".aasx", ".json", ".xml")


def test_looks_like_aas_json() -> None:
    assert looks_like_aas_json(json.dumps({"assetAdministrationShells": []}))
    assert looks_like_aas_json(json.dumps({"submodels": [{"id": "x"}]}))
    assert not looks_like_aas_json(json.dumps({"name": "package", "version": "1.0"}))
    assert not looks_like_aas_json("not json at all")


def test_looks_like_aas_xml() -> None:
    assert looks_like_aas_xml('<aas:environment xmlns:aas="https://admin-shell.io/aas/3/0">')
    assert looks_like_aas_xml("<environment><assetAdministrationShells/></environment>")
    assert not looks_like_aas_xml("<rss><channel></channel></rss>")


def test_is_probably_aas_file(tmp_path: Path) -> None:
    aas_json = tmp_path / "env.json"
    aas_json.write_text(json.dumps({"assetAdministrationShells": [{"id": "x"}]}))
    assert is_probably_aas_file(aas_json)

    other_json = tmp_path / "package.json"
    other_json.write_text(json.dumps({"dependencies": {}}))
    assert not is_probably_aas_file(other_json)

    aas_xml = tmp_path / "env.xml"
    aas_xml.write_text('<aas:environment xmlns:aas="https://admin-shell.io/aas/3/0"/>')
    assert is_probably_aas_file(aas_xml)

    # AASX is accepted on structure (validated later by the verify pipeline).
    aasx = tmp_path / "model.aasx"
    aasx.write_bytes(b"PK\x03\x04")
    assert is_probably_aas_file(aasx)


def test_extract_aas_links_matches_all_formats() -> None:
    html = """
    <a href="a.aasx">x</a>
    <a href="b.json">y</a>
    <a href="sub/c.xml">z</a>
    <a href="ignore.txt">n</a>
    """
    links = _extract_aas_links(html, "https://h.example/dir/")
    assert links == [
        "https://h.example/dir/a.aasx",
        "https://h.example/dir/b.json",
        "https://h.example/dir/sub/c.xml",
    ]


def test_extract_aasx_links_still_aasx_only() -> None:
    html = '<a href="a.aasx">x</a><a href="b.json">y</a>'
    assert _extract_aasx_links(html, "https://h/") == ["https://h/a.aasx"]
