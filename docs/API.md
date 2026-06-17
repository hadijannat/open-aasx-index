# Query API

The Open AASX Index publishes a **static HTTP query API** alongside the catalog.
Because the site is hosted on GitHub Pages, the "endpoints" are pre-computed JSON
documents at predictable URLs — fetch them with any HTTP client, no server
required.

Base URL: `https://hadijannat.github.io/open-aasx-index/api/v1/`

> Forks/redeployments: the examples below use this project's GitHub Pages base
> URL. If you host the catalog elsewhere, treat everything from `api/v1/` on as a
> relative path and prepend your own domain.

Every entry returned by the API is **enriched with submodel-template
classification**, so you can distinguish *current* IDTA templates from
*deprecated* ones (see [Current vs. deprecated](#current-vs-deprecated)).

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `index.json` | API descriptor: totals, facet counts, and the list of endpoints |
| `entries.json` | All catalog entries, template-enriched |
| `templates.json` | The IDTA submodel-template registry + per-template usage counts |
| `semantic-ids.json` | Every semantic ID found, classified, with usage counts and entry refs |
| `by-status/{status}.json` | Entries filtered by `verified` \| `parseable` \| `failed` |
| `by-source/{source}.json` | Entries filtered by `github` \| `seed` \| `sitemap` \| `commoncrawl` \| `aas_server` |
| `by-format/{format}.json` | Entries filtered by AAS serialization: `aasx` \| `json` \| `xml` |
| `by-template-status/{status}.json` | Entries filtered by `current` \| `deprecated` \| `unknown` |

### AAS serialization formats

The index covers all three AAS serializations — **AASX** (Part 5 OPC package),
**JSON** and **XML** (Part 1 mappings) — discovered as files on the web, plus
live **instances** enumerated from AAS servers. (PDF is not an AAS format; it
only appears as a supplementary file inside an AASX.) Each entry records its
`file.format`, exposed via the `by-format/` endpoints and the `format` facet.

### Example: find files using *current* templates only

```bash
curl https://hadijannat.github.io/open-aasx-index/api/v1/by-template-status/current.json
```

```python
import requests

base = "https://hadijannat.github.io/open-aasx-index/api/v1"
current = requests.get(f"{base}/by-template-status/current.json").json()
print(f"{current['count']} files use current IDTA submodel templates")
```

## Current vs. deprecated

IDTA revises submodel templates over time, so older versions get **deprecated**.
A catalog built from old sample files tends to contain mostly deprecated
versions (e.g. Digital Nameplate `1/0` and `2/0`) rather than the current one
(`3/0`).

Each semantic ID is classified into one of:

- `current` — matches a known IDTA template family at its latest (or newer) version
- `deprecated` — a known family, but an older version; `superseded_by` points to the current semantic ID
- `unknown` — not matched against the curated registry

The registry lives in [`harvest/templates.py`](../harvest/templates.py) and is a
curated, community-maintainable best-effort list. To add or correct a template,
add a `TemplateFamily` entry there.

## Local querying (CLI)

The same query engine is available offline via the `harvest-query` command (or
`python -m harvest.query`):

```bash
# All files using current templates
harvest-query --template-status current

# Only JSON-serialized AAS files
harvest-query --format json

# Count deprecated Digital Nameplate usages
harvest-query --template-family digital-nameplate --template-status deprecated --count

# Free-text search, paginated
harvest-query nameplate --limit 20 --offset 0
```
