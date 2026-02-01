# Open AASX Index

An open, automated index of publicly available AASX (Asset Administration Shell) files with compliance verification.

## Overview

Open AASX Index discovers, verifies, and catalogs AASX files from across the web. Every file is checked against the official AAS specification using [aas-test-engines](https://github.com/admin-shell-io/aas-test-engines).

### Verification Policy

Each discovered AASX file receives one of three statuses:

| Status | Description |
|--------|-------------|
| `verified` | Passes all aas-test-engines compliance checks |
| `parseable` | Opens as valid ZIP/AASX but fails some compliance checks |
| `failed` | Cannot be downloaded or opened |

### Data Format

The catalog is published in multiple formats:

- `public/catalog.json` — Full catalog as JSON array
- `public/catalog.csv` — Key fields for quick export
- `public/stats.json` — Aggregate statistics

See [data/schema/catalog.schema.json](data/schema/catalog.schema.json) for the complete record schema.

## Quick Start

### Browse the Index

Visit **[open-aasx-index.github.io](https://open-aasx-index.github.io)** to search and filter the catalog.

### Use the Data

```bash
# Download the full catalog
curl -O https://open-aasx-index.github.io/catalog.json

# Query with jq
jq '.[] | select(.verification.status == "verified")' catalog.json
```

### Run Locally

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the harvester (dry run)
python -m harvest --dry-run

# Run with limits
python -m harvest --max-validate 10 --max-github 20
```

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Discovery      │────▶│  Download    │────▶│  Verify     │
│  - GitHub       │     │  - Size cap  │     │  - aas-test │
│  - Seeds        │     │  - Zip-bomb  │     │  - engines  │
│  - Sitemap      │     │    detection │     │             │
│  - CommonCrawl  │     └──────────────┘     └─────────────┘
└─────────────────┘                                 │
                                                    ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Publish        │◀────│  Extract     │◀────│  Catalog    │
│  - JSON/CSV     │     │  - BaSyx SDK │     │  - NDJSON   │
│  - Stats        │     │  - Metadata  │     │  - Dedup    │
│  - Website      │     │              │     │             │
└─────────────────┘     └──────────────┘     └─────────────┘
```

## Safety Measures

The harvester includes multiple safety checks:

- **Size limits**: Max 50MB download, 100MB uncompressed
- **Zip-bomb detection**: Entry count, compression ratio checks
- **Rate limiting**: Respects API limits (GitHub: 10 req/min)
- **Exponential backoff**: On 429/403 responses

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Adding Sources

To suggest new AASX sources, edit `SOURCES.yml` and submit a PR. URLs must:
- Point to publicly accessible pages
- Contain links to `.aasx` files
- Be from reputable sources

### Reporting Issues

- Found a broken link? Open an issue
- Verification incorrect? Include the file URL and expected result
- Security concern? See [SECURITY.md](SECURITY.md)

## License

This project is dedicated to the public domain under [CC0 1.0](LICENSE).

The catalog data (`public/`) is also CC0. Individual AASX files retain their original licenses as noted in the `provenance.license` field.

## Acknowledgments

- [aas-test-engines](https://github.com/admin-shell-io/aas-test-engines) for compliance verification
- [BaSyx Python SDK](https://github.com/eclipse-basyx/basyx-python-sdk) for metadata extraction
- [IDTA](https://industrialdigitaltwin.org/) for the AAS specification
