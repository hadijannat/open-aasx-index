# Contributing to Open AASX Index

Thank you for your interest in contributing! This document explains how to participate.

## Ways to Contribute

### 1. Add AASX Sources

The easiest way to contribute is by adding new sources of AASX files:

1. Fork this repository
2. Edit `SOURCES.yml` to add your source
3. Submit a pull request

**Source requirements:**
- URL must be publicly accessible (no authentication)
- Page must contain direct links to `.aasx` files
- Source should be reputable (company sites, research institutions, official repositories)

**Example SOURCES.yml entry:**
```yaml
sources:
  - url: https://example.com/aasx-samples
    name: Example Corp Samples
    type: seed
    notes: Official sample files from Example Corp
```

### 2. Report Issues

- **Broken links**: If a file URL no longer works, open an issue with the URL
- **Incorrect verification**: If you believe a file was incorrectly classified, provide the URL and explain the expected result
- **New features**: Suggest improvements to the harvester or website

### 3. Improve Code

We welcome code contributions:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `pytest`
5. Run linting: `ruff check . && mypy harvest`
6. Submit a pull request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/open-aasx-index.git
cd open-aasx-index

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .
mypy harvest
```

## Pull Request Process

1. **Update tests**: Add tests for new functionality
2. **Update docs**: Update README.md if needed
3. **Follow style**: Run `ruff format .` before committing
4. **One thing at a time**: Keep PRs focused on a single change
5. **Describe changes**: Write a clear PR description

## Code Style

- Python 3.11+ features are welcome
- Type hints are required for all public functions
- Use `ruff` for formatting and linting
- Keep functions small and focused

## Commit Messages

Use conventional commit format:

```
type(scope): description

feat(sources): add sitemap discovery
fix(downloader): handle redirect loops
docs(readme): clarify verification policy
test(verify): add edge case for empty files
```

## Questions?

Open a [discussion](https://github.com/open-aasx-index/open-aasx-index/discussions) for questions or ideas.

## License

By contributing, you agree that your contributions will be licensed under CC0 1.0.
