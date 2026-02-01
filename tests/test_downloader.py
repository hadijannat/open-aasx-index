"""Tests for the safe downloader module."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import pytest
import respx

from harvest.downloader import (
    DownloadFailedError,
    DownloadResult,
    FileTooLargeError,
    ZipBombError,
    download_file,
    inspect_zip,
)


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for test downloads."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def create_zip_bytes(files: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """Create a ZIP file in memory with the given files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def create_test_aasx(content: bytes = b"test content") -> bytes:
    """Create a minimal valid AASX (ZIP) file."""
    return create_zip_bytes({"test.xml": content})


class TestInspectZip:
    """Tests for ZIP inspection."""

    def test_valid_zip(self, temp_dir: Path) -> None:
        """Test inspection of a valid, safe ZIP file."""
        zip_path = temp_dir / "valid.zip"
        zip_path.write_bytes(create_zip_bytes({"file1.txt": b"hello", "file2.txt": b"world"}))

        result = inspect_zip(zip_path)

        assert result.is_safe is True
        assert result.entry_count == 2
        assert result.reason is None

    def test_too_many_entries(self, temp_dir: Path) -> None:
        """Test detection of ZIP with too many entries."""
        # Create a ZIP with more than MAX_ZIP_ENTRIES
        files = {f"file{i}.txt": b"x" for i in range(600)}
        zip_path = temp_dir / "many_entries.zip"
        zip_path.write_bytes(create_zip_bytes(files))

        result = inspect_zip(zip_path)

        assert result.is_safe is False
        assert result.entry_count == 600
        assert "Too many entries" in result.reason

    def test_suspicious_compression_ratio(self, temp_dir: Path) -> None:
        """Test detection of suspicious compression ratio (potential zip bomb)."""
        # Create highly compressible content (repeated bytes)
        # This creates a very high compression ratio
        huge_content = b"\x00" * (10 * 1024 * 1024)  # 10MB of zeros
        zip_path = temp_dir / "suspicious.zip"
        zip_path.write_bytes(create_zip_bytes({"big.bin": huge_content}))

        result = inspect_zip(zip_path)

        # With 10MB of zeros, compression ratio will be very high
        assert result.compression_ratio > 100
        assert result.is_safe is False
        assert "compression ratio" in result.reason.lower()

    def test_invalid_zip(self, temp_dir: Path) -> None:
        """Test handling of invalid ZIP file."""
        invalid_path = temp_dir / "invalid.zip"
        invalid_path.write_bytes(b"not a zip file")

        result = inspect_zip(invalid_path)

        assert result.is_safe is False
        assert "Invalid ZIP file" in result.reason


class TestDownloadFile:
    """Tests for file download functionality."""

    @respx.mock
    def test_successful_download(self, temp_dir: Path) -> None:
        """Test successful file download."""
        url = "https://example.com/test.aasx"
        content = create_test_aasx(b"test aasx content")

        respx.head(url).respond(200, headers={"Content-Length": str(len(content))})
        respx.get(url).respond(
            200,
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )

        result = download_file(url, dest_dir=temp_dir)

        assert isinstance(result, DownloadResult)
        assert result.path.exists()
        assert result.size_bytes == len(content)
        assert len(result.sha256) == 64
        assert result.filename == "test.aasx"

    @respx.mock
    def test_file_too_large_from_header(self, temp_dir: Path) -> None:
        """Test rejection of file that's too large (from Content-Length)."""
        url = "https://example.com/huge.aasx"

        respx.head(url).respond(
            200,
            headers={"Content-Length": str(100 * 1024 * 1024)},  # 100MB
        )

        with pytest.raises(FileTooLargeError):
            download_file(url, dest_dir=temp_dir, max_bytes=50 * 1024 * 1024)

    @respx.mock
    def test_file_too_large_during_download(self, temp_dir: Path) -> None:
        """Test rejection of file that exceeds size during streaming."""
        url = "https://example.com/sneaky.aasx"
        # Server lies about content-length or doesn't provide it
        content = b"x" * (2 * 1024 * 1024)  # 2MB

        respx.head(url).respond(405)  # HEAD not allowed
        respx.get(url).respond(200, content=content)

        with pytest.raises(FileTooLargeError):
            download_file(url, dest_dir=temp_dir, max_bytes=1 * 1024 * 1024)

    @respx.mock
    def test_zip_bomb_rejected(self, temp_dir: Path) -> None:
        """Test rejection of zip bomb."""
        url = "https://example.com/bomb.aasx"
        # Create a zip with very high compression ratio
        huge_content = b"\x00" * (20 * 1024 * 1024)  # 20MB of zeros
        content = create_zip_bytes({"bomb.bin": huge_content})

        respx.head(url).respond(200, headers={"Content-Length": str(len(content))})
        respx.get(url).respond(200, content=content)

        with pytest.raises(ZipBombError):
            download_file(url, dest_dir=temp_dir)

    @respx.mock
    def test_skip_zip_check(self, temp_dir: Path) -> None:
        """Test that zip check can be skipped."""
        url = "https://example.com/unchecked.bin"
        # Not a zip file, just binary
        content = b"binary content"

        respx.head(url).respond(200, headers={"Content-Length": str(len(content))})
        respx.get(url).respond(200, content=content)

        result = download_file(url, dest_dir=temp_dir, check_zip=False)

        assert result.path.exists()
        assert result.path.read_bytes() == content

    @respx.mock
    def test_filename_from_content_disposition(self, temp_dir: Path) -> None:
        """Test filename extraction from Content-Disposition header."""
        url = "https://example.com/download"
        content = create_test_aasx()

        respx.head(url).respond(200)
        respx.get(url).respond(
            200,
            content=content,
            headers={"Content-Disposition": 'attachment; filename="custom_name.aasx"'},
        )

        result = download_file(url, dest_dir=temp_dir)

        assert result.filename == "custom_name.aasx"

    @respx.mock
    def test_http_error(self, temp_dir: Path) -> None:
        """Test handling of HTTP errors."""
        url = "https://example.com/notfound.aasx"

        respx.head(url).respond(404)
        respx.get(url).respond(404)

        with pytest.raises(DownloadFailedError):
            download_file(url, dest_dir=temp_dir)


class TestDownloadResultSha256:
    """Tests for SHA256 hash calculation."""

    @respx.mock
    def test_sha256_correctness(self, temp_dir: Path) -> None:
        """Test that SHA256 hash is calculated correctly."""
        import hashlib

        url = "https://example.com/hash_test.aasx"
        content = create_test_aasx(b"unique content for hashing")
        expected_hash = hashlib.sha256(content).hexdigest()

        respx.head(url).respond(200)
        respx.get(url).respond(200, content=content)

        result = download_file(url, dest_dir=temp_dir)

        assert result.sha256 == expected_hash
