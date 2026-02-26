# Contributing to PePeRS

Thanks for your interest in PePeRS!

## Quick Start

```bash
git clone https://github.com/gptcompany/pepers.git
cd pepers
uv sync --all-extras
python -m pytest tests/unit/ -q  # Run tests
```

## Development

- **Python 3.10+** with `uv` for dependency management
- **Tests**: `pytest` with 1,000+ unit tests — all must pass before merging
- **Style**: No frameworks, stdlib-first. Follow existing patterns
- **Commits**: Conventional commits (`feat:`, `fix:`, `ci:`, `test:`, `docs:`)

## Pull Requests

1. Fork and create a feature branch
2. Write tests for new functionality
3. Ensure `python -m pytest tests/unit/ -q` passes
4. Submit PR against `main` — CI must be green

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for service structure.

Each service is a standalone HTTP server in `services/`. Shared code lives in `shared/`.

## Issues

Use the issue templates for bugs and feature requests. Include the service name and relevant logs.
