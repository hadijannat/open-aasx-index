"""AASX compliance verification using aas-test-engines."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harvest.config import REPORTS_DIR, VerificationStatus


@dataclass
class VerificationResult:
    """Result of verifying an AASX file."""

    status: VerificationStatus
    exit_code: int | None
    engine: str
    summary: str
    errors: list[str] = field(default_factory=list)
    report_path: str | None = None
    raw_output: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for catalog storage."""
        result: dict[str, Any] = {
            "status": self.status,
            "engine": self.engine,
            "exit_code": self.exit_code,
            "summary": self.summary,
        }
        if self.errors:
            result["errors"] = self.errors
        if self.report_path:
            result["report_path"] = self.report_path
        return result


def _get_engine_version() -> str:
    """Get the aas-test-engines version string."""
    try:
        from aas_test_engines import version

        return f"aas-test-engines/{version}"
    except ImportError:
        return "aas-test-engines/unknown"


def _parse_json_output(output: str) -> dict[str, Any] | None:
    """Parse JSON output from aas-test-engines."""
    try:
        parsed: dict[str, Any] = json.loads(output)
        return parsed
    except json.JSONDecodeError:
        return None


def _count_errors(result: dict[str, Any]) -> tuple[int, list[str]]:
    """Count errors and extract error messages from test result.

    Returns:
        Tuple of (error_count, error_messages)
    """
    errors: list[str] = []

    def traverse(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            # Check if this node is a test result
            if "ok" in node and node.get("ok") is False:
                message = node.get("message", "Unknown error")
                if path:
                    errors.append(f"{path}: {message}")
                else:
                    errors.append(message)

            # Recurse into sub_checks
            for key, value in node.items():
                if key == "sub_checks" and isinstance(value, list):
                    for i, sub in enumerate(value):
                        name = sub.get("name", f"check_{i}")
                        traverse(sub, f"{path}/{name}" if path else name)
                elif isinstance(value, (dict, list)):
                    traverse(value, path)
        elif isinstance(node, list):
            for item in node:
                traverse(item, path)

    traverse(result)
    return len(errors), errors[:10]  # Limit to 10 errors


def verify_file(
    file_path: Path,
    save_report: bool = True,
    reports_dir: Path = REPORTS_DIR,
    sha256: str | None = None,
) -> VerificationResult:
    """Verify an AASX file for AAS compliance.

    Args:
        file_path: Path to the AASX file
        save_report: Whether to save the full report to disk
        reports_dir: Directory for saving reports
        sha256: SHA256 hash of the file (for report naming)

    Returns:
        VerificationResult with status and details
    """
    engine = _get_engine_version()

    # Check file exists
    if not file_path.exists():
        return VerificationResult(
            status="failed",
            exit_code=None,
            engine=engine,
            summary="File not found",
            errors=[f"File does not exist: {file_path}"],
        )

    # Run aas-test-engines check_file
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "aas_test_engines",
                "check_file",
                str(file_path),
                "--format",
                "aasx",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )
    except subprocess.TimeoutExpired:
        return VerificationResult(
            status="failed",
            exit_code=None,
            engine=engine,
            summary="Verification timed out",
            errors=["Verification exceeded 2 minute timeout"],
        )
    except FileNotFoundError:
        return VerificationResult(
            status="failed",
            exit_code=None,
            engine=engine,
            summary="aas-test-engines not found",
            errors=["aas-test-engines is not installed"],
        )

    exit_code = result.returncode
    raw_output = _parse_json_output(result.stdout)

    # Save report if requested
    report_path: str | None = None
    if save_report and raw_output:
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_name = sha256 if sha256 else file_path.stem
        report_file = reports_dir / f"{report_name}.json"
        report_file.write_text(json.dumps(raw_output, indent=2))
        report_path = str(report_file.relative_to(reports_dir.parent.parent))

    # Determine status based on exit code
    if exit_code == 0:
        return VerificationResult(
            status="verified",
            exit_code=exit_code,
            engine=engine,
            summary="All compliance checks passed",
            report_path=report_path,
            raw_output=raw_output,
        )

    # Non-zero exit code - check if file was parseable
    if raw_output is not None:
        # File was parsed but failed some checks
        error_count, errors = _count_errors(raw_output)
        return VerificationResult(
            status="parseable",
            exit_code=exit_code,
            engine=engine,
            summary=f"File parseable but {error_count} compliance check(s) failed",
            errors=errors,
            report_path=report_path,
            raw_output=raw_output,
        )

    # Could not parse at all
    stderr_msg = result.stderr.strip() if result.stderr else "Unknown error"
    return VerificationResult(
        status="failed",
        exit_code=exit_code,
        engine=engine,
        summary="File could not be parsed",
        errors=[stderr_msg[:500]],  # Limit error message length
        report_path=report_path,
    )


def verify_files(
    files: list[tuple[Path, str]],
    reports_dir: Path = REPORTS_DIR,
) -> list[tuple[str, VerificationResult]]:
    """Verify multiple AASX files.

    Args:
        files: List of (file_path, sha256) tuples
        reports_dir: Directory for saving reports

    Returns:
        List of (sha256, VerificationResult) tuples
    """
    results = []
    for file_path, sha256 in files:
        result = verify_file(
            file_path=file_path,
            save_report=True,
            reports_dir=reports_dir,
            sha256=sha256,
        )
        results.append((sha256, result))
    return results


def get_verification_summary(results: list[VerificationResult]) -> dict[str, int]:
    """Get summary counts by verification status.

    Args:
        results: List of verification results

    Returns:
        Dictionary with counts per status
    """
    counts: dict[str, int] = {"verified": 0, "parseable": 0, "failed": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts
