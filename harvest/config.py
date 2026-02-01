"""Configuration constants and CLI argument parsing."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# File size limits
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_ZIP_ENTRIES = 500

# Compression ratio threshold for zip-bomb detection
MAX_COMPRESSION_RATIO = 100

# Rate limits
GITHUB_REQUESTS_PER_MINUTE = 10
WEB_REQUESTS_PER_SECOND = 1

# HTTP settings
MAX_REDIRECTS = 5
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "OpenAASXIndex/0.1 (+https://github.com/open-aasx-index/open-aasx-index)"

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
REPORTS_DIR = DATA_DIR / "reports"
SCHEMA_DIR = DATA_DIR / "schema"
PUBLIC_DIR = PROJECT_ROOT / "public"
SOURCES_FILE = PROJECT_ROOT / "SOURCES.yml"

# Catalog files
CATALOG_NDJSON = DATA_DIR / "catalog.ndjson"
CATALOG_JSON = PUBLIC_DIR / "catalog.json"
CATALOG_CSV = PUBLIC_DIR / "catalog.csv"
STATS_JSON = PUBLIC_DIR / "stats.json"

# State files
STATE_FILE = STATE_DIR / "state.json"

SourceType = Literal["github", "seed", "sitemap", "commoncrawl"]
VerificationStatus = Literal["verified", "parseable", "failed"]


@dataclass
class HarvestConfig:
    """Configuration for a harvest run."""

    max_validate: int = 200
    max_github: int = 100
    max_web: int = 50
    dry_run: bool = False
    source: str | None = None
    verbose: bool = False

    # Derived paths
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    state_dir: Path = field(default_factory=lambda: STATE_DIR)
    reports_dir: Path = field(default_factory=lambda: REPORTS_DIR)
    public_dir: Path = field(default_factory=lambda: PUBLIC_DIR)

    def __post_init__(self) -> None:
        """Ensure directories exist."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.public_dir.mkdir(parents=True, exist_ok=True)


def parse_args(args: list[str] | None = None) -> HarvestConfig:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="harvest",
        description="Open AASX Index harvester - discover, verify, and catalog AASX files",
    )

    parser.add_argument(
        "--max-validate",
        type=int,
        default=200,
        help="Maximum files to verify per run (default: 200)",
    )
    parser.add_argument(
        "--max-github",
        type=int,
        default=100,
        help="Maximum items from GitHub (default: 100)",
    )
    parser.add_argument(
        "--max-web",
        type=int,
        default=50,
        help="Maximum items from web sources (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without executing",
    )
    parser.add_argument(
        "--source",
        choices=["github", "seeds", "sitemap", "commoncrawl"],
        help="Run specific source only",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    parsed = parser.parse_args(args)

    return HarvestConfig(
        max_validate=parsed.max_validate,
        max_github=parsed.max_github,
        max_web=parsed.max_web,
        dry_run=parsed.dry_run,
        source=parsed.source,
        verbose=parsed.verbose,
    )
