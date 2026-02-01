"""Tests for the verification module."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harvest.verify import (
    VerificationResult,
    _count_errors,
    _parse_json_output,
    get_verification_summary,
    verify_file,
)


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def create_minimal_aasx(dest: Path) -> Path:
    """Create a minimal AASX file for testing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # Minimal OPC content
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
        zf.writestr("aasx/test.json", '{"test": true}')

    dest.write_bytes(buffer.getvalue())
    return dest


class TestParseJsonOutput:
    """Tests for JSON output parsing."""

    def test_valid_json(self) -> None:
        """Test parsing valid JSON."""
        output = '{"ok": true, "message": "test"}'
        result = _parse_json_output(output)
        assert result == {"ok": True, "message": "test"}

    def test_invalid_json(self) -> None:
        """Test parsing invalid JSON returns None."""
        result = _parse_json_output("not json")
        assert result is None

    def test_empty_string(self) -> None:
        """Test parsing empty string returns None."""
        result = _parse_json_output("")
        assert result is None


class TestCountErrors:
    """Tests for error counting."""

    def test_no_errors(self) -> None:
        """Test counting when no errors."""
        result = {"ok": True, "message": "All good"}
        count, errors = _count_errors(result)
        assert count == 0
        assert errors == []

    def test_single_error(self) -> None:
        """Test counting single error."""
        result = {"ok": False, "message": "Something failed"}
        count, errors = _count_errors(result)
        assert count == 1
        assert "Something failed" in errors[0]

    def test_nested_errors(self) -> None:
        """Test counting errors in nested sub_checks."""
        result = {
            "ok": False,
            "sub_checks": [
                {"name": "check1", "ok": True},
                {"name": "check2", "ok": False, "message": "Error in check2"},
                {
                    "name": "check3",
                    "ok": False,
                    "message": "Error in check3",
                    "sub_checks": [
                        {"name": "nested", "ok": False, "message": "Nested error"},
                    ],
                },
            ],
        }
        count, errors = _count_errors(result)
        # Should find: root error, check2, check3, nested
        assert count >= 3

    def test_error_limit(self) -> None:
        """Test that errors are limited to 10."""
        result = {
            "sub_checks": [
                {"name": f"check{i}", "ok": False, "message": f"Error {i}"}
                for i in range(20)
            ]
        }
        count, errors = _count_errors(result)
        assert count == 20
        assert len(errors) == 10  # Limited to 10


class TestVerifyFile:
    """Tests for file verification."""

    def test_file_not_found(self, temp_dir: Path) -> None:
        """Test verification of non-existent file."""
        result = verify_file(temp_dir / "nonexistent.aasx", save_report=False)

        assert result.status == "failed"
        assert result.exit_code is None
        assert "not found" in result.summary.lower() or "not exist" in result.errors[0].lower()

    @patch("harvest.verify.subprocess.run")
    def test_verified_status(self, mock_run: MagicMock, temp_dir: Path) -> None:
        """Test that exit code 0 means verified."""
        # Create a test file
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        # Mock successful verification
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"ok": true}',
            stderr="",
        )

        result = verify_file(test_file, save_report=False)

        assert result.status == "verified"
        assert result.exit_code == 0
        assert "passed" in result.summary.lower()

    @patch("harvest.verify.subprocess.run")
    def test_parseable_status(self, mock_run: MagicMock, temp_dir: Path) -> None:
        """Test that non-zero exit with JSON output means parseable."""
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        # Mock verification with failures but parseable
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"ok": false, "message": "Compliance check failed"}',
            stderr="",
        )

        result = verify_file(test_file, save_report=False)

        assert result.status == "parseable"
        assert result.exit_code == 1
        assert "parseable" in result.summary.lower()

    @patch("harvest.verify.subprocess.run")
    def test_failed_status(self, mock_run: MagicMock, temp_dir: Path) -> None:
        """Test that non-zero exit without JSON output means failed."""
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        # Mock verification failure (can't even parse)
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",  # No JSON output
            stderr="Error: Invalid AASX format",
        )

        result = verify_file(test_file, save_report=False)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert "Invalid AASX" in result.errors[0]

    @patch("harvest.verify.subprocess.run")
    def test_timeout(self, mock_run: MagicMock, temp_dir: Path) -> None:
        """Test handling of verification timeout."""
        test_file = create_minimal_aasx(temp_dir / "test.aasx")

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=120)

        result = verify_file(test_file, save_report=False)

        assert result.status == "failed"
        assert "timed out" in result.summary.lower()

    @patch("harvest.verify.subprocess.run")
    def test_report_saved(self, mock_run: MagicMock, temp_dir: Path) -> None:
        """Test that report is saved when requested."""
        test_file = create_minimal_aasx(temp_dir / "test.aasx")
        reports_dir = temp_dir / "reports"

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"ok": true, "checks": []}',
            stderr="",
        )

        result = verify_file(
            test_file,
            save_report=True,
            reports_dir=reports_dir,
            sha256="abc123",
        )

        assert result.report_path is not None
        report_file = reports_dir / "abc123.json"
        assert report_file.exists()
        content = json.loads(report_file.read_text())
        assert content["ok"] is True


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_to_dict_minimal(self) -> None:
        """Test conversion to dict with minimal fields."""
        result = VerificationResult(
            status="verified",
            exit_code=0,
            engine="test/1.0",
            summary="All passed",
        )
        d = result.to_dict()

        assert d["status"] == "verified"
        assert d["exit_code"] == 0
        assert d["engine"] == "test/1.0"
        assert d["summary"] == "All passed"
        assert "errors" not in d
        assert "report_path" not in d

    def test_to_dict_with_errors(self) -> None:
        """Test conversion to dict with errors."""
        result = VerificationResult(
            status="failed",
            exit_code=1,
            engine="test/1.0",
            summary="Failed",
            errors=["Error 1", "Error 2"],
            report_path="reports/test.json",
        )
        d = result.to_dict()

        assert d["errors"] == ["Error 1", "Error 2"]
        assert d["report_path"] == "reports/test.json"


class TestGetVerificationSummary:
    """Tests for verification summary."""

    def test_empty_results(self) -> None:
        """Test summary of empty results."""
        summary = get_verification_summary([])
        assert summary == {"verified": 0, "parseable": 0, "failed": 0}

    def test_mixed_results(self) -> None:
        """Test summary of mixed results."""
        results = [
            VerificationResult("verified", 0, "test", "ok"),
            VerificationResult("verified", 0, "test", "ok"),
            VerificationResult("parseable", 1, "test", "partial"),
            VerificationResult("failed", 1, "test", "bad"),
        ]
        summary = get_verification_summary(results)

        assert summary["verified"] == 2
        assert summary["parseable"] == 1
        assert summary["failed"] == 1
