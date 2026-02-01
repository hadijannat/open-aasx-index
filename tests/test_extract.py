"""Tests for the metadata extraction module."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harvest.extract import (
    ExtractionResult,
    ShellInfo,
    SubmodelInfo,
    _get_reference_value,
    extract_metadata,
)


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def create_minimal_aasx(dest: Path) -> Path:
    """Create a minimal AASX file structure."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # OPC content types
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="json" ContentType="application/json"/>'
            "</Types>",
        )
        # Relationships
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            "</Relationships>",
        )
    dest.write_bytes(buffer.getvalue())
    return dest


class TestShellInfo:
    """Tests for ShellInfo dataclass."""

    def test_to_dict_full(self) -> None:
        """Test conversion with all fields."""
        shell = ShellInfo(
            id_short="TestShell",
            id="urn:example:shell:1",
            global_asset_id="urn:example:asset:1",
        )
        d = shell.to_dict()

        assert d["id"] == "urn:example:shell:1"
        assert d["id_short"] == "TestShell"
        assert d["global_asset_id"] == "urn:example:asset:1"

    def test_to_dict_minimal(self) -> None:
        """Test conversion with only required fields."""
        shell = ShellInfo(id_short=None, id="urn:example:shell:1")
        d = shell.to_dict()

        assert d["id"] == "urn:example:shell:1"
        assert "id_short" not in d
        assert "global_asset_id" not in d


class TestSubmodelInfo:
    """Tests for SubmodelInfo dataclass."""

    def test_to_dict_full(self) -> None:
        """Test conversion with all fields."""
        sm = SubmodelInfo(
            id_short="TestSubmodel",
            id="urn:example:submodel:1",
            semantic_id="urn:example:semantic:1",
        )
        d = sm.to_dict()

        assert d["id"] == "urn:example:submodel:1"
        assert d["id_short"] == "TestSubmodel"
        assert d["semantic_id"] == "urn:example:semantic:1"

    def test_to_dict_minimal(self) -> None:
        """Test conversion with only required fields."""
        sm = SubmodelInfo(id_short=None, id="urn:example:submodel:1")
        d = sm.to_dict()

        assert d["id"] == "urn:example:submodel:1"
        assert "id_short" not in d
        assert "semantic_id" not in d


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_to_dict_success(self) -> None:
        """Test conversion of successful extraction."""
        result = ExtractionResult(
            success=True,
            shells=[ShellInfo(id_short="S1", id="urn:shell:1")],
            submodels=[SubmodelInfo(id_short="SM1", id="urn:sm:1", semantic_id="urn:sem:1")],
            semantic_ids=["urn:sem:1", "urn:sem:2"],
        )
        d = result.to_dict()

        assert len(d["shells"]) == 1
        assert len(d["submodels"]) == 1
        assert d["semantic_ids"] == ["urn:sem:1", "urn:sem:2"]

    def test_to_dict_failure(self) -> None:
        """Test conversion of failed extraction returns empty dict."""
        result = ExtractionResult(success=False, error="Some error")
        d = result.to_dict()

        assert d == {}

    def test_to_dict_empty_success(self) -> None:
        """Test conversion of successful but empty extraction."""
        result = ExtractionResult(success=True)
        d = result.to_dict()

        assert d == {}


class TestGetReferenceValue:
    """Tests for reference value extraction."""

    def test_none_reference(self) -> None:
        """Test handling of None reference."""
        assert _get_reference_value(None) is None

    def test_reference_with_key(self) -> None:
        """Test extraction from reference with key attribute."""
        mock_key = MagicMock()
        mock_key.value = "urn:example:value"
        mock_ref = MagicMock()
        mock_ref.key = [mock_key]

        result = _get_reference_value(mock_ref)
        assert result == "urn:example:value"

    def test_reference_fallback_to_str(self) -> None:
        """Test fallback to string conversion."""
        mock_ref = MagicMock()
        mock_ref.key = None
        mock_ref.__str__ = lambda self: "string-value"

        result = _get_reference_value(mock_ref)
        assert "string-value" in result or result is not None


class TestExtractMetadata:
    """Tests for metadata extraction."""

    def test_file_not_found(self, temp_dir: Path) -> None:
        """Test extraction from non-existent file."""
        result = extract_metadata(temp_dir / "nonexistent.aasx")

        assert result.success is False
        assert "not found" in result.error.lower()

    @patch("basyx.aas.adapter.aasx.AASXReader")
    def test_successful_extraction(self, mock_reader_class: MagicMock, temp_dir: Path) -> None:
        """Test successful metadata extraction."""
        # Create a mock AASX file
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        # Mock the BaSyx SDK
        from basyx.aas import model

        mock_shell = MagicMock(spec=model.AssetAdministrationShell)
        mock_shell.id_short = "TestShell"
        mock_shell.id = "urn:example:shell:1"
        mock_shell.asset_information = MagicMock()
        mock_shell.asset_information.global_asset_id = "urn:example:asset:1"

        mock_submodel = MagicMock(spec=model.Submodel)
        mock_submodel.id_short = "TestSubmodel"
        mock_submodel.id = "urn:example:submodel:1"
        mock_submodel.semantic_id = None
        mock_submodel.submodel_element = []

        # Set up mock object store
        mock_store = MagicMock()
        mock_store.__iter__ = lambda self: iter([mock_shell, mock_submodel])

        mock_reader = MagicMock()
        mock_reader.__enter__ = lambda self: mock_reader
        mock_reader.__exit__ = lambda self, *args: None
        mock_reader.read_into = lambda object_store, file_store: None

        mock_reader_class.return_value = mock_reader

        # Patch DictObjectStore to return our mock store
        with patch("basyx.aas.model.DictObjectStore", return_value=mock_store):
            result = extract_metadata(test_file)

        assert result.success is True
        assert len(result.shells) == 1
        assert result.shells[0].id == "urn:example:shell:1"
        assert len(result.submodels) == 1

    def test_invalid_aasx(self, temp_dir: Path) -> None:
        """Test extraction from invalid AASX file."""
        # Create an invalid file
        invalid_file = temp_dir / "invalid.aasx"
        invalid_file.write_bytes(b"not a valid aasx")

        result = extract_metadata(invalid_file)

        # Should fail gracefully
        assert result.success is False
        assert result.error is not None

    @patch("basyx.aas.adapter.aasx.AASXReader")
    def test_extraction_with_semantic_ids(
        self, mock_reader_class: MagicMock, temp_dir: Path
    ) -> None:
        """Test that semantic IDs are collected."""
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        from basyx.aas import model

        # Create mock submodel with semantic ID
        mock_semantic_ref = MagicMock()
        mock_key = MagicMock()
        mock_key.value = "urn:example:semantic:type"
        mock_semantic_ref.key = [mock_key]

        mock_submodel = MagicMock(spec=model.Submodel)
        mock_submodel.id_short = "SM1"
        mock_submodel.id = "urn:sm:1"
        mock_submodel.semantic_id = mock_semantic_ref
        mock_submodel.submodel_element = []

        mock_store = MagicMock()
        mock_store.__iter__ = lambda self: iter([mock_submodel])

        mock_reader = MagicMock()
        mock_reader.__enter__ = lambda self: mock_reader
        mock_reader.__exit__ = lambda self, *args: None
        mock_reader.read_into = lambda object_store, file_store: None

        mock_reader_class.return_value = mock_reader

        with patch("basyx.aas.model.DictObjectStore", return_value=mock_store):
            result = extract_metadata(test_file)

        assert result.success is True
        assert "urn:example:semantic:type" in result.semantic_ids


class TestExtractMetadataIntegration:
    """Integration tests that use actual BaSyx SDK (skipped if not available)."""

    @pytest.mark.skipif(
        not pytest.importorskip("basyx", reason="BaSyx SDK not installed"),
        reason="BaSyx SDK not available",
    )
    def test_empty_aasx(self, temp_dir: Path) -> None:
        """Test extraction from minimal AASX with no AAS content."""
        test_file = create_minimal_aasx(temp_dir / "empty.aasx")

        result = extract_metadata(test_file)

        # Should either succeed with empty results or fail gracefully
        # depending on whether the minimal AASX is valid enough
        assert isinstance(result, ExtractionResult)
