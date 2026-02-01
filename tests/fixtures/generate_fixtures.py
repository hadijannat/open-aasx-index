#!/usr/bin/env python3
"""Generate test fixture files for AASX testing."""

import io
import json
import zipfile
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def create_valid_aasx() -> bytes:
    """Create a minimal valid AASX file.

    This follows the OPC (Open Packaging Convention) format with
    basic AAS structure that should pass compliance checks.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Content Types (required by OPC)
        content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="json" ContentType="application/json"/>
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
</Types>"""
        zf.writestr("[Content_Types].xml", content_types)

        # Root relationships - must include aasx-origin pointing to /aasx/
        root_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Type="http://admin-shell.io/aasx/relationships/aasx-origin" Target="/aasx/aasx-origin" Id="rId1"/>
</Relationships>"""
        zf.writestr("_rels/.rels", root_rels)

        # AASX origin marker file (can be empty)
        zf.writestr("aasx/aasx-origin", "")

        # AAS JSON content (minimal valid structure)
        aas_content = {
            "assetAdministrationShells": [
                {
                    "idShort": "TestShell",
                    "id": "urn:example:aas:test:1",
                    "assetInformation": {
                        "assetKind": "Instance",
                        "globalAssetId": "urn:example:asset:test:1",
                    },
                    "modelType": "AssetAdministrationShell",
                }
            ],
            "submodels": [
                {
                    "idShort": "TestSubmodel",
                    "id": "urn:example:submodel:test:1",
                    "semanticId": {
                        "type": "ExternalReference",
                        "keys": [
                            {
                                "type": "GlobalReference",
                                "value": "urn:example:semantic:test",
                            }
                        ],
                    },
                    "submodelElements": [],
                    "modelType": "Submodel",
                }
            ],
            "conceptDescriptions": [],
        }
        zf.writestr("aasx/aas.json", json.dumps(aas_content, indent=2))

        # AASX origin relationships - points to the aas-spec file
        aasx_origin_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Type="http://admin-shell.io/aasx/relationships/aas-spec" Target="/aasx/aas.json" Id="rId1"/>
</Relationships>"""
        zf.writestr("aasx/_rels/aasx-origin.rels", aasx_origin_rels)

    return buffer.getvalue()


def create_parseable_aasx() -> bytes:
    """Create an AASX that opens but has compliance issues.

    This file can be read as a ZIP and has some AAS structure,
    but violates compliance rules (missing required fields, etc).
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Content Types
        content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="json" ContentType="application/json"/>
</Types>"""
        zf.writestr("[Content_Types].xml", content_types)

        # Incomplete AAS (missing required fields)
        aas_content = {
            "assetAdministrationShells": [
                {
                    # Missing idShort and other required fields
                    "id": "incomplete-aas",
                }
            ],
            "submodels": [],
        }
        zf.writestr("aasx/aas.json", json.dumps(aas_content))

    return buffer.getvalue()


def create_zipbomb() -> bytes:
    """Create a file with suspicious compression characteristics.

    This creates a small compressed file that would expand to a
    very large size, triggering zip-bomb detection.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Create highly compressible content (zeros compress extremely well)
        # 20MB of zeros will compress to a tiny file
        huge_content = b"\x00" * (20 * 1024 * 1024)
        zf.writestr("bomb.bin", huge_content)

    return buffer.getvalue()


def main():
    """Generate all test fixtures."""
    print("Generating test fixtures...")

    # Valid AASX
    valid_path = FIXTURES_DIR / "valid.aasx"
    valid_path.write_bytes(create_valid_aasx())
    print(f"  Created: {valid_path} ({valid_path.stat().st_size} bytes)")

    # Parseable but non-compliant AASX
    parseable_path = FIXTURES_DIR / "parseable.aasx"
    parseable_path.write_bytes(create_parseable_aasx())
    print(f"  Created: {parseable_path} ({parseable_path.stat().st_size} bytes)")

    # Zip bomb
    zipbomb_path = FIXTURES_DIR / "zipbomb.zip"
    zipbomb_path.write_bytes(create_zipbomb())
    print(f"  Created: {zipbomb_path} ({zipbomb_path.stat().st_size} bytes)")

    print("Done!")


if __name__ == "__main__":
    main()
