"""AAS serialization format detection and lightweight content sniffing.

The Asset Administration Shell spec defines three serializations: AASX (Part 5,
an OPC/zip package), JSON and XML (Part 1 mappings). PDF is *not* an AAS format
— it can only appear as a supplementary file inside an AASX.

Discovery sources cast a wide net (any ``.json``/``.xml`` link on a page), so
before a downloaded JSON/XML file is treated as an AAS instance we sniff its
content to avoid indexing unrelated config files.
"""

from __future__ import annotations

import json
from pathlib import Path

AasFormat = str  # "aasx" | "json" | "xml"

# Extensions discovery sources look for. AASX first (most specific).
AAS_FILE_EXTENSIONS: tuple[str, ...] = (".aasx", ".json", ".xml")

# Top-level keys that mark a JSON document as an AAS Environment (Part 1 JSON).
_AAS_JSON_KEYS = ("assetAdministrationShells", "submodels", "conceptDescriptions")

# Substrings that mark an XML document as an AAS Environment (any spec version).
_AAS_XML_MARKERS = ("admin-shell.io/aas", "assetAdministrationShells", "<aas:environment")

# How many bytes to read when sniffing (AAS markers appear near the top).
_SNIFF_BYTES = 8192


def detect_format(name: str | Path) -> AasFormat | None:
    """Return the AAS format implied by a filename/URL, or None if unsupported."""
    lower = str(name).lower()
    if lower.endswith(".aasx"):
        return "aasx"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".xml"):
        return "xml"
    return None


def looks_like_aas_json(text: str) -> bool:
    """True if ``text`` parses as a JSON object with AAS Environment keys."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return False
    return isinstance(data, dict) and any(key in data for key in _AAS_JSON_KEYS)


def looks_like_aas_xml(text: str) -> bool:
    """True if ``text`` contains an AAS XML namespace/root marker."""
    return any(marker in text for marker in _AAS_XML_MARKERS)


def is_probably_aas_file(file_path: Path, fmt: AasFormat | None = None) -> bool:
    """Content-sniff a downloaded file to confirm it is an AAS serialization.

    AASX is accepted on structure (the download/verify pipeline validates the
    zip); JSON/XML are sniffed so non-AAS documents are skipped rather than
    recorded as failures.
    """
    fmt = fmt or detect_format(file_path)
    if fmt == "aasx":
        return True
    if fmt not in ("json", "xml"):
        return False
    try:
        head = file_path.read_text(encoding="utf-8", errors="ignore")[:_SNIFF_BYTES]
    except OSError:
        return False
    if fmt == "json":
        # Sniff against the whole file: a truncated head may not be valid JSON.
        try:
            full = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return looks_like_aas_json(full)
    return looks_like_aas_xml(head)
