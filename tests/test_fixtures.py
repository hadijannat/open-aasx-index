"""Tests using the fixture files."""

from __future__ import annotations

from pathlib import Path

import pytest

from harvest.downloader import inspect_zip
from harvest.extract import extract_metadata
from harvest.verify import verify_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestValidAasx:
    """Tests with the valid.aasx fixture."""

    @pytest.fixture
    def valid_aasx(self) -> Path:
        """Path to valid.aasx fixture."""
        return FIXTURES_DIR / "valid.aasx"

    def test_zip_inspection_passes(self, valid_aasx: Path) -> None:
        """Test that valid.aasx passes zip inspection."""
        result = inspect_zip(valid_aasx)
        assert result.is_safe is True
        assert result.reason is None

    def test_metadata_extraction(self, valid_aasx: Path) -> None:
        """Test that metadata can be extracted from valid.aasx."""
        result = extract_metadata(valid_aasx)

        # Should succeed
        assert result.success is True

        # Should find the shell
        assert len(result.shells) == 1
        assert result.shells[0].id == "urn:example:aas:test:1"
        assert result.shells[0].id_short == "TestShell"

        # Should find the submodel
        assert len(result.submodels) == 1
        assert result.submodels[0].id == "urn:example:submodel:test:1"

        # Should find semantic IDs
        assert "urn:example:semantic:test" in result.semantic_ids


class TestParseableAasx:
    """Tests with the parseable.aasx fixture."""

    @pytest.fixture
    def parseable_aasx(self) -> Path:
        """Path to parseable.aasx fixture."""
        return FIXTURES_DIR / "parseable.aasx"

    def test_zip_inspection_passes(self, parseable_aasx: Path) -> None:
        """Test that parseable.aasx passes zip inspection."""
        result = inspect_zip(parseable_aasx)
        assert result.is_safe is True

    def test_metadata_extraction_graceful(self, parseable_aasx: Path) -> None:
        """Test that metadata extraction handles incomplete files gracefully."""
        result = extract_metadata(parseable_aasx)

        # May or may not succeed depending on how strict the parser is
        # But should not raise an exception
        assert isinstance(result.success, bool)


class TestZipBomb:
    """Tests with the zipbomb.zip fixture."""

    @pytest.fixture
    def zipbomb(self) -> Path:
        """Path to zipbomb.zip fixture."""
        return FIXTURES_DIR / "zipbomb.zip"

    def test_zip_inspection_detects_bomb(self, zipbomb: Path) -> None:
        """Test that zip-bomb is detected."""
        result = inspect_zip(zipbomb)

        assert result.is_safe is False
        assert result.reason is not None
        # Should detect high compression ratio
        assert "compression ratio" in result.reason.lower() or "size" in result.reason.lower()

    def test_compression_ratio_is_high(self, zipbomb: Path) -> None:
        """Test that compression ratio is detected as suspicious."""
        result = inspect_zip(zipbomb)

        # 20MB compressed to ~20KB = ratio of ~1000x
        assert result.compression_ratio > 100


class TestEndToEnd:
    """End-to-end tests using fixtures."""

    def test_valid_aasx_workflow(self) -> None:
        """Test full workflow with valid.aasx."""
        valid_path = FIXTURES_DIR / "valid.aasx"

        # 1. Zip inspection should pass
        inspection = inspect_zip(valid_path)
        assert inspection.is_safe is True

        # 2. Metadata extraction should succeed
        metadata = extract_metadata(valid_path)
        assert metadata.success is True
        assert len(metadata.shells) > 0

        # 3. Verification runs (result depends on aas-test-engines)
        verification = verify_file(valid_path, save_report=False)
        # Should at least not crash
        assert verification.status in ("verified", "parseable", "failed")

    def test_zipbomb_rejected_before_verification(self) -> None:
        """Test that zip-bomb is caught before expensive verification."""
        zipbomb_path = FIXTURES_DIR / "zipbomb.zip"

        # Inspection should fail
        inspection = inspect_zip(zipbomb_path)
        assert inspection.is_safe is False

        # In real workflow, we wouldn't proceed to verification
        # This test documents that behavior
