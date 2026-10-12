# JARVIS

Personal bilingual (Brazilian Portuguese / English) voice assistant for Windows, inspired by
J.A.R.V.I.S. from the Iron Man films: push a key or say its name, ask, and it acts on the PC,
searches the web and answers out loud, in the manner of a formal British butler.

> **Status:** work in progress, Phase 3 (brain): simple commands are resolved locally by
> rules; everything else goes to Claude Haiku, which can use the same tools. A full bilingual
> README with demo, architecture diagram and installation guide arrives in the final phase.

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
| "Me lembra em 20 minutos de tirar a pizza" / "Remind me to call John at 6 pm" | Reminders, kept across restarts; also list and cancel them |
| "Vai chover amanhã?" / "What's the weather like in London?" | Weather now, today or tomorrow (Open-Meteo, no key) |
| "Procura o arquivo currículo", "Abre o segundo" / "Find the file report" | Searches Desktop, Documents and Downloads; programs are only shown, never run |
| "Fala em inglês", "Idioma automático" / "Speak Portuguese" | Locks the reply language, or goes back to replying in the language spoken |
| Anything else: "Quem descobriu o Brasil?", "E amanhã?" | Claude Haiku answers briefly, remembering the last few exchanges |

## Requirements

- Windows 10/11 and an NVIDIA GPU (speech recognition runs on CUDA)
- [uv](https://docs.astral.sh/uv/), which installs the right Python (3.14) by itself
- A microphone, ideally a headset

The first `uv sync` downloads about 1.5 GB (CUDA libraries included); the first run downloads
the speech model (~1.5 GB) and the offline voices (~120 MB).

## Claude API key (optional)

Without a key JARVIS still runs every command in the table above except the free questions.

1. In the [Anthropic Console](https://console.anthropic.com/), buy a small amount of credit,
   keep auto-reload off and set a monthly spend limit.
2. Create an API key and copy `.env.example` to `.env`; put the key after
   `ANTHROPIC_API_KEY=`. `.env` is git-ignored: never paste the key anywhere else.
3. `uv run jarvis --check` validates the key without spending tokens.

JARVIS records the estimated cost of every request in `data/jarvis.db`, warns at US$ 4.00
and stops calling the API at US$ 4.90 (`[budget]` in the configuration).

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
| `uv run jarvis --check` | Checks Python, GPU, CUDA, configuration, hotkey, audio devices, the API key and spending so far |
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
