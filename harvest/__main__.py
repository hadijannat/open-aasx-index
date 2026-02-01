"""CLI entrypoint for the Open AASX Index harvester."""

from __future__ import annotations

import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harvest.config import HarvestConfig, parse_args
from harvest.downloader import (
    DownloadError,
    DownloadResult,
    download_file,
)
from harvest.extract import ExtractionResult, extract_metadata
from harvest.publish import publish_catalog
from harvest.sources.commoncrawl import CommonCrawlState, discover_commoncrawl
from harvest.sources.github import GitHubSearchState, discover_github
from harvest.sources.seeds import discover_seeds, get_allowed_domains, load_sources_config
from harvest.sources.sitemap import discover_sitemaps
from harvest.storage import (
    CatalogEntry,
    CatalogStorage,
    HarvestState,
    StateStorage,
    deduplicate_candidates,
)
from harvest.verify import VerificationResult, verify_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def discover_candidates(
    config: HarvestConfig,
    state: HarvestState,
    sources_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run discovery from all configured sources.

    Args:
        config: Harvest configuration
        state: Current harvest state
        sources_config: Loaded SOURCES.yml configuration

    Returns:
        List of candidate dictionaries
    """
    candidates: list[dict[str, Any]] = []
    allowed_domains = get_allowed_domains(sources_config)

    # GitHub source
    if config.source is None or config.source == "github":
        logger.info("Running GitHub discovery...")
        github_state = GitHubSearchState()
        if state.github_cursor:
            github_state.code_search_page = int(state.github_cursor)

        github_candidates, new_github_state = discover_github(
            max_results=config.max_github,
            state=github_state,
        )
        candidates.extend(github_candidates)
        state.github_cursor = str(new_github_state.code_search_page)
        logger.info(f"GitHub: found {len(github_candidates)} candidates")

    # Seeds source
    if config.source is None or config.source == "seeds":
        logger.info("Running seed discovery...")
        seed_candidates = discover_seeds(
            config=sources_config,
            max_results=config.max_web,
        )
        candidates.extend(seed_candidates)
        logger.info(f"Seeds: found {len(seed_candidates)} candidates")

    # Sitemap source
    if config.source is None or config.source == "sitemap":
        logger.info("Running sitemap discovery...")
        # Get base URLs from sources that have sitemaps
        base_urls = [
            s["url"] for s in sources_config.get("sources", []) if s.get("type") == "sitemap"
        ]
        if base_urls:
            sitemap_candidates = discover_sitemaps(
                base_urls=base_urls,
                allowed_domains=allowed_domains,
                max_results=config.max_web,
            )
            candidates.extend(sitemap_candidates)
            logger.info(f"Sitemap: found {len(sitemap_candidates)} candidates")

    # Common Crawl source
    if config.source is None or config.source == "commoncrawl":
        logger.info("Running Common Crawl discovery...")
        cc_state = CommonCrawlState()
        if state.commoncrawl_cursor:
            cc_state.last_cursor = state.commoncrawl_cursor

        cc_candidates, new_cc_state = discover_commoncrawl(
            allowed_domains=allowed_domains,
            max_results=config.max_web,
            state=cc_state,
        )
        candidates.extend(cc_candidates)
        state.commoncrawl_cursor = new_cc_state.last_cursor
        logger.info(f"Common Crawl: found {len(cc_candidates)} candidates")

    return candidates


def process_candidate(
    candidate: dict[str, Any],
    config: HarvestConfig,
) -> CatalogEntry | None:
    """Download, verify, and extract metadata from a candidate.

    Args:
        candidate: Candidate dictionary with url, source_type, etc.
        config: Harvest configuration

    Returns:
        CatalogEntry if successful, None otherwise
    """
    url = candidate.get("url")
    if not url:
        return None

    logger.info(f"Processing: {url}")

    # Create temp directory for this candidate
    with tempfile.TemporaryDirectory(prefix="aasx_") as temp_dir:
        temp_path = Path(temp_dir)

        # Download
        try:
            download_result: DownloadResult = download_file(
                url=url,
                dest_dir=temp_path,
            )
        except DownloadError as e:
            logger.warning(f"Download failed for {url}: {e}")
            # Create failed entry
            return CatalogEntry(
                id=f"sha256-{'0' * 64}",  # Placeholder
                file={"url": url, "sha256": ""},
                provenance={
                    "source_type": candidate.get("source_type", "unknown"),
                    "source_ref": candidate.get("source_ref"),
                    "license": candidate.get("license"),
                    "discovered_at": datetime.now(UTC).isoformat(),
                },
                verification={
                    "status": "failed",
                    "summary": f"Download failed: {e}",
                },
            )

        sha256 = download_result.sha256
        entry_id = f"sha256-{sha256}"

        # Verify
        verification_result: VerificationResult = verify_file(
            file_path=download_result.path,
            save_report=True,
            reports_dir=config.reports_dir,
            sha256=sha256,
        )

        # Extract metadata
        extraction_result: ExtractionResult = extract_metadata(download_result.path)

        # Build catalog entry
        now = datetime.now(UTC).isoformat()

        return CatalogEntry(
            id=entry_id,
            file={
                "url": url,
                "size_bytes": download_result.size_bytes,
                "sha256": sha256,
                "filename": download_result.filename,
            },
            provenance={
                "source_type": candidate.get("source_type", "unknown"),
                "source_ref": candidate.get("source_ref"),
                "license": candidate.get("license"),
                "discovered_at": now,
                "last_verified_at": now,
            },
            verification=verification_result.to_dict(),
            metadata=extraction_result.to_dict(),
        )


def run_harvest(config: HarvestConfig) -> int:
    """Run the harvest pipeline.

    Args:
        config: Harvest configuration

    Returns:
        Exit code (0 for success)
    """
    logger.info("Starting harvest run")
    logger.info(f"  max_validate: {config.max_validate}")
    logger.info(f"  max_github: {config.max_github}")
    logger.info(f"  max_web: {config.max_web}")
    logger.info(f"  dry_run: {config.dry_run}")
    logger.info(f"  source: {config.source or 'all'}")

    # Load sources configuration
    sources_config = load_sources_config()

    # Load state
    state_storage = StateStorage()
    state = state_storage.load()

    # Load catalog
    catalog_storage = CatalogStorage()

    # Update state from existing catalog
    state_storage.update_from_catalog(state, catalog_storage)
    logger.info(f"Loaded state: {len(state.seen_urls)} known URLs")

    # Discover candidates
    candidates = discover_candidates(config, state, sources_config)
    logger.info(f"Total candidates discovered: {len(candidates)}")

    # Deduplicate
    new_candidates = deduplicate_candidates(candidates, state)
    logger.info(f"New candidates after deduplication: {len(new_candidates)}")

    if config.dry_run:
        logger.info("Dry run - showing planned actions:")
        for candidate in new_candidates[: config.max_validate]:
            logger.info(f"  Would process: {candidate.get('url')}")
        return 0

    # Process candidates
    new_entries: list[CatalogEntry] = []
    processed = 0

    for candidate in new_candidates:
        if processed >= config.max_validate:
            break

        entry = process_candidate(candidate, config)
        if entry:
            new_entries.append(entry)
            state.seen_urls.add(candidate.get("url", ""))
            if entry.file.get("sha256"):
                state.seen_sha256.add(entry.file["sha256"])

        processed += 1

    logger.info(f"Processed {processed} candidates, {len(new_entries)} new entries")

    # Update catalog
    if new_entries:
        existing_entries = catalog_storage.read_all()

        # Merge: update existing entries by ID, add new ones
        entries_by_id = {e.id: e for e in existing_entries}
        for entry in new_entries:
            entries_by_id[entry.id] = entry

        all_entries = list(entries_by_id.values())
        catalog_storage.write_all(all_entries)
        logger.info(f"Catalog updated: {len(all_entries)} total entries")

    # Save state
    state.mark_run()
    state_storage.save(state)
    logger.info("State saved")

    # Publish artifacts
    logger.info("Publishing artifacts...")
    publish_catalog(catalog_storage, config.public_dir)
    logger.info("Artifacts published")

    # Summary
    verified = sum(1 for e in new_entries if e.verification.get("status") == "verified")
    parseable = sum(1 for e in new_entries if e.verification.get("status") == "parseable")
    failed = sum(1 for e in new_entries if e.verification.get("status") == "failed")

    logger.info("Run complete:")
    logger.info(f"  New entries: {len(new_entries)}")
    logger.info(f"    verified: {verified}")
    logger.info(f"    parseable: {parseable}")
    logger.info(f"    failed: {failed}")

    return 0


def main() -> int:
    """Main entry point."""
    try:
        config = parse_args()

        if config.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        return run_harvest(config)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
