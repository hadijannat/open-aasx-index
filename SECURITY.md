# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Open AASX Index, please report it responsibly:

1. **Do NOT open a public issue**
2. Email the maintainers directly (see repository settings for contact)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond within 48 hours and work with you to understand and address the issue.

## Security Measures

The harvester includes several security measures:

### Download Safety

- **Size limits**: Downloads capped at 50MB
- **Uncompressed limits**: Max 100MB uncompressed content
- **Entry limits**: Max 500 files per archive
- **Compression ratio**: Detects suspicious compression ratios (zip bombs)
- **Redirect limits**: Max 5 HTTP redirects

### Rate Limiting

- GitHub API: 10 requests/minute
- Web crawling: 1 request/second per domain
- Exponential backoff on 429/403 responses

### Data Validation

- All URLs validated before crawling
- Domain allowlist for external sources
- JSON schema validation for catalog entries

## Scope

This security policy covers:

- The harvester Python code (`harvest/`)
- The static website (`site/`)
- GitHub Actions workflows (`.github/workflows/`)

It does NOT cover:

- Third-party AASX files (we only index them, not audit their contents)
- External websites linked in `SOURCES.yml`

## Known Limitations

- AASX files may contain arbitrary content; we verify AAS compliance, not security
- URLs in the catalog link to external resources we don't control
- The harvester runs with network access and file system writes

## Updates

Security updates will be released as needed. Watch the repository for notifications.
