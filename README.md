# JARVIS

Personal bilingual (Brazilian Portuguese / English) voice assistant for Windows, inspired by
J.A.R.V.I.S. from the Iron Man films: push a key or say its name, ask, and it acts on the PC,
searches the web and answers out loud, in the manner of a formal British butler.

> **Status:** work in progress, Phase 0 (foundation). A full bilingual README with demo,
> architecture diagram and installation guide arrives in the final phase.

## Requirements

- Windows 10/11 and an NVIDIA GPU (speech recognition runs on CUDA)
- [uv](https://docs.astral.sh/uv/), which installs the right Python (3.14) by itself

## Quick start

```bash
uv sync
uv run jarvis --check
uv run jarvis
```

Configuration lives in `config/default.toml`; put personal overrides in `config/local.toml`
(see `config/local.example.toml`) and secrets in `.env` (see `.env.example`).

## Development

```bash
uv run ruff format
uv run ruff check
uv run mypy
uv run pytest
```

Design decisions are recorded in [docs/DECISIONS.md](docs/DECISIONS.md) and the architecture
in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE)
