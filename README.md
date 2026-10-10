# JARVIS

Personal bilingual (Brazilian Portuguese / English) voice assistant for Windows, inspired by
J.A.R.V.I.S. from the Iron Man films: push a key or say its name, ask, and it acts on the PC,
searches the web and answers out loud, in the manner of a formal British butler.

> **Status:** work in progress, Phase 2 (hands): local commands in Portuguese and English,
> resolved by rules without any LLM. A full bilingual README with demo, architecture diagram
> and installation guide arrives in the final phase.

## What it can do so far

| Say (pt / en) | JARVIS |
|---|---|
| "Abre o Spotify" / "Open Spotify" | Opens any app in the Start menu (approximate names, aliases) |
| "Abre o YouTube" / "Go to github dot com" | Opens favourite sites or a spoken domain |
| "Como está o PC?" / "System status" | CPU, RAM, GPU load and temperature (details in the log) |
| "Pausa a música", "Próxima" / "Pause", "Next song" | Media keys (works with Spotify Free) |
| "Volume em 30%", "Mais alto", "Mudo" / "Volume up", "Mute" | Master volume |
| "Bloqueia o computador" / "Lock the computer" | Locks the PC |
| "Desliga o computador", "Fecha o Discord" / "Restart my PC", "Close Discord" | Asks "Shall I proceed, sir?" and acts only on a spoken yes |

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
