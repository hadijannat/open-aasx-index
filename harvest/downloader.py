"""Safe file downloader with size limits and zip-bomb detection."""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from harvest.config import (
    MAX_COMPRESSION_RATIO,
    MAX_DOWNLOAD_BYTES,
    MAX_REDIRECTS,
    MAX_UNCOMPRESSED_BYTES,
    MAX_ZIP_ENTRIES,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)
from harvest.rate_limiter import get_rate_limiter


class DownloadError(Exception):
    """Base exception for download errors."""

    pass


class FileTooLargeError(DownloadError):
    """File exceeds size limit."""

    pass


class ZipBombError(DownloadError):
    """Suspicious archive detected."""

    pass


class TooManyRedirectsError(DownloadError):
    """Too many HTTP redirects."""

    pass


class DownloadFailedError(DownloadError):
    """Download failed with HTTP error."""

    pass


@dataclass
class DownloadResult:
    """Result of a successful download."""

    path: Path
    size_bytes: int
    sha256: str
    content_type: str | None = None
    filename: str | None = None


@dataclass
class ZipInspection:
    """Results of inspecting a ZIP file for safety."""

    entry_count: int
    total_compressed: int
    total_uncompressed: int
    compression_ratio: float
    is_safe: bool
    reason: str | None = None


def _get_headers() -> dict[str, str]:
    """Get default HTTP headers."""
    return {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }


def _extract_filename(response: httpx.Response, url: str) -> str | None:
    """Extract filename from Content-Disposition header or URL."""
    # Try Content-Disposition header
    content_disp = response.headers.get("content-disposition", "")
    if "filename=" in content_disp:
        # Parse filename from header
        for part in content_disp.split(";"):
            part = part.strip()
            if part.startswith("filename="):
                filename: str = part[9:].strip("\"'")
                return filename

    # Fall back to URL path
    path = httpx.URL(url).path
    if path and "/" in path:
        return path.rsplit("/", 1)[-1] or None

    return None


def inspect_zip(file_path: Path) -> ZipInspection:
    """Inspect a ZIP file for potential zip-bomb characteristics.

    Args:
        file_path: Path to the ZIP file

    Returns:
        ZipInspection with safety analysis
    """
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            infos = zf.infolist()
            entry_count = len(infos)
            total_compressed = sum(info.compress_size for info in infos)
            total_uncompressed = sum(info.file_size for info in infos)

            # Calculate compression ratio
            if total_compressed > 0:
                compression_ratio = total_uncompressed / total_compressed
            else:
                compression_ratio = 0.0

            # Safety checks
            reasons = []

            if entry_count > MAX_ZIP_ENTRIES:
                reasons.append(f"Too many entries: {entry_count} > {MAX_ZIP_ENTRIES}")

            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                mb = total_uncompressed / (1024 * 1024)
                max_mb = MAX_UNCOMPRESSED_BYTES / (1024 * 1024)
                reasons.append(f"Uncompressed size too large: {mb:.1f}MB > {max_mb:.1f}MB")

            if compression_ratio > MAX_COMPRESSION_RATIO:
                reasons.append(
                    f"Suspicious compression ratio: {compression_ratio:.1f}x > {MAX_COMPRESSION_RATIO}x"
                )

            is_safe = len(reasons) == 0
            reason = "; ".join(reasons) if reasons else None

            return ZipInspection(
                entry_count=entry_count,
                total_compressed=total_compressed,
                total_uncompressed=total_uncompressed,
                compression_ratio=compression_ratio,
                is_safe=is_safe,
                reason=reason,
            )

    except zipfile.BadZipFile as e:
        return ZipInspection(
            entry_count=0,
            total_compressed=0,
            total_uncompressed=0,
            compression_ratio=0.0,
            is_safe=False,
            reason=f"Invalid ZIP file: {e}",
        )


def download_file(
    url: str,
    dest_dir: Path | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    check_zip: bool = True,
) -> DownloadResult:
    """Download a file with safety checks.

    Args:
        url: URL to download
        dest_dir: Directory to save file (uses temp dir if None)
        max_bytes: Maximum file size in bytes
        check_zip: Whether to inspect ZIP files for bombs

    Returns:
        DownloadResult with file path and metadata

    Raises:
        FileTooLargeError: If file exceeds size limit
        ZipBombError: If ZIP file fails safety inspection
        TooManyRedirectsError: If too many redirects
        DownloadFailedError: If HTTP request fails
    """
    rate_limiter = get_rate_limiter()
    rate_limiter.wait_sync("web")

    # Create destination directory
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="aasx_"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(
            headers=_get_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        ) as client:
            # First, do a HEAD request to check size
            try:
                head_response = client.head(url)
                content_length = head_response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    mb = int(content_length) / (1024 * 1024)
                    max_mb = max_bytes / (1024 * 1024)
                    raise FileTooLargeError(
                        f"File too large: {mb:.1f}MB > {max_mb:.1f}MB (from Content-Length)"
                    )
            except httpx.HTTPError:
                # HEAD might not be supported, continue with GET
                pass

            # Stream the download
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise DownloadFailedError(
                        f"HTTP {response.status_code}: {response.reason_phrase}"
                    )

                # Extract filename
                filename = _extract_filename(response, url) or "download.aasx"
                dest_path = dest_dir / filename

                # Download with size limit
                hasher = hashlib.sha256()
                total_bytes = 0

                with dest_path.open("wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            # Clean up partial download
                            f.close()
                            dest_path.unlink(missing_ok=True)
                            mb = total_bytes / (1024 * 1024)
                            max_mb = max_bytes / (1024 * 1024)
                            raise FileTooLargeError(f"File too large: >{mb:.1f}MB > {max_mb:.1f}MB")
                        f.write(chunk)
                        hasher.update(chunk)

                sha256 = hasher.hexdigest()
                content_type = response.headers.get("content-type")

                # Check ZIP safety if it looks like a ZIP/AASX
                if check_zip and (
                    filename.endswith((".zip", ".aasx"))
                    or content_type in ("application/zip", "application/octet-stream")
                ):
                    inspection = inspect_zip(dest_path)
                    if not inspection.is_safe:
                        # Clean up suspicious file
                        dest_path.unlink(missing_ok=True)
                        raise ZipBombError(f"Suspicious archive: {inspection.reason}")

                return DownloadResult(
                    path=dest_path,
                    size_bytes=total_bytes,
                    sha256=sha256,
                    content_type=content_type,
                    filename=filename,
                )

    except httpx.TooManyRedirects as e:
        raise TooManyRedirectsError(f"Too many redirects (>{MAX_REDIRECTS}) for {url}") from e
    except httpx.HTTPError as e:
        raise DownloadFailedError(f"HTTP error: {e}") from e


async def download_file_async(
    url: str,
    dest_dir: Path | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    check_zip: bool = True,
) -> DownloadResult:
    """Async version of download_file.

    Args:
        url: URL to download
        dest_dir: Directory to save file (uses temp dir if None)
        max_bytes: Maximum file size in bytes
        check_zip: Whether to inspect ZIP files for bombs

    Returns:
        DownloadResult with file path and metadata

    Raises:
        Same as download_file
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.acquire("web")

    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="aasx_"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(
            headers=_get_headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        ) as client:
            # HEAD request for size check
            try:
                head_response = await client.head(url)
                content_length = head_response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    mb = int(content_length) / (1024 * 1024)
                    max_mb = max_bytes / (1024 * 1024)
                    raise FileTooLargeError(
                        f"File too large: {mb:.1f}MB > {max_mb:.1f}MB (from Content-Length)"
                    )
            except httpx.HTTPError:
                pass

            # Stream download
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise DownloadFailedError(
                        f"HTTP {response.status_code}: {response.reason_phrase}"
                    )

                filename = _extract_filename(response, url) or "download.aasx"
                dest_path = dest_dir / filename

                hasher = hashlib.sha256()
                total_bytes = 0

                with dest_path.open("wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            f.close()
                            dest_path.unlink(missing_ok=True)
                            mb = total_bytes / (1024 * 1024)
                            max_mb = max_bytes / (1024 * 1024)
                            raise FileTooLargeError(f"File too large: >{mb:.1f}MB > {max_mb:.1f}MB")
                        f.write(chunk)
                        hasher.update(chunk)

                sha256 = hasher.hexdigest()
                content_type = response.headers.get("content-type")

                if check_zip and (
                    filename.endswith((".zip", ".aasx"))
                    or content_type in ("application/zip", "application/octet-stream")
                ):
                    inspection = inspect_zip(dest_path)
                    if not inspection.is_safe:
                        dest_path.unlink(missing_ok=True)
                        raise ZipBombError(f"Suspicious archive: {inspection.reason}")

                return DownloadResult(
                    path=dest_path,
                    size_bytes=total_bytes,
                    sha256=sha256,
                    content_type=content_type,
                    filename=filename,
                )

    except httpx.TooManyRedirects as e:
        raise TooManyRedirectsError(f"Too many redirects (>{MAX_REDIRECTS}) for {url}") from e
    except httpx.HTTPError as e:
        raise DownloadFailedError(f"HTTP error: {e}") from e
