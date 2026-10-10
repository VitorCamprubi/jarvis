# JARVIS

Personal bilingual (Brazilian Portuguese / English) voice assistant for Windows, inspired by
J.A.R.V.I.S. from the Iron Man films: push a key or say its name, ask, and it acts on the PC,
searches the web and answers out loud, in the manner of a formal British butler.

> **Status:** work in progress, Phase 1 (ears and voice): press a hotkey, speak, and JARVIS
> repeats what it understood, in the language you used. A full bilingual README with demo,
> architecture diagram and installation guide arrives in the final phase.

## Requirements

- Windows 10/11 and an NVIDIA GPU (speech recognition runs on CUDA)
- [uv](https://docs.astral.sh/uv/), which installs the right Python (3.14) by itself
- A microphone, ideally a headset

The first `uv sync` downloads about 1.5 GB (CUDA libraries included); the first run downloads
the speech model (~1.5 GB) and the offline voices (~120 MB).

## Quick start

```bash
uv sync
uv run jarvis --check
uv run jarvis
```

Then press **Ctrl+Alt+J**, speak, and wait for the reply. Press the hotkey again while it is
listening to cancel; Ctrl+C in the console quits.

| Command | What it does |
|---|---|
| `uv run jarvis --check` | Checks Python, GPU, CUDA, configuration, hotkey and audio devices |
| `uv run jarvis --devices` | Lists microphones and audio outputs |
| `uv run jarvis --mic-test` | Measures background noise and your voice, suggests the VAD level |

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
