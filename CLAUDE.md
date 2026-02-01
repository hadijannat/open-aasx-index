# CLAUDE.md

Project-specific context for Claude Code.

## Project Overview

Open AASX Index is an automated catalog of publicly available AASX (Asset Administration Shell) files. It discovers, verifies, and indexes AASX files from GitHub and curated seed sources.

## Key Commands

```bash
# Run harvester (dry run)
python -m harvest --dry-run

# Run harvester with limits
python -m harvest --max-validate 10 --max-github 20

# Run tests
pytest

# Lint and format
ruff check . && ruff format .
mypy harvest

# Build site locally
cd site && npm ci && npm run build
```

## Architecture

- `harvest/` - Python package for discovering and validating AASX files
- `site/` - React/Vite website for browsing the catalog
- `data/` - Catalog data (NDJSON), schemas, state files
- `public/` - Published outputs (catalog.json, catalog.csv, stats.json)
- `.github/workflows/` - CI and weekly harvest automation

## Important Files

- `SOURCES.yml` - Seed URLs and GitHub topics for discovery
- `data/schema/catalog.schema.json` - JSON schema for catalog entries
- `site/vite.config.ts` - Vite config (base path set for GitHub Pages)

## GitHub Pages

The site is deployed to `hadijannat.github.io/open-aasx-index/`. Key config:
- Vite `base`: `/open-aasx-index/`
- React Router `basename`: `/open-aasx-index`
- Data fetch uses `import.meta.env.BASE_URL`

## Workflows

- **CI** (`ci.yml`): Runs on push, validates schema and linting
- **Weekly Harvest** (`weekly_harvest.yml`): Runs Sundays at 03:00 UTC, can be triggered manually

## Schema Notes

- `file.sha256` is optional (empty for failed downloads)
- `verification.status`: `verified`, `parseable`, or `failed`
- IDs use format `sha256-{hash}` (64 hex chars)

## Conventions

- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, etc.)
- Python: Type hints required, use ruff for formatting
- TypeScript: Strict mode enabled
