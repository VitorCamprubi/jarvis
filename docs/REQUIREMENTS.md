# Requirements: the brief and how each item was met

Every requirement of the original brief, with its status and where it was decided, built and
tested. **Met** means as asked; **Changed** means changed with the owner's approval, as
recorded in the ADR.

## Constraints

| Requirement | Status | How |
|---|---|---|
| Zero cost: local AI, no paid API | Changed | The owner chose the Claude API with a hard US$ 5 cap ([ADR-009](DECISIONS.md#adr-009-claude-api-haiku-55-as-the-only-llm-provider-in-v1), [ADR-010](DECISIONS.md#adr-010-us-5-spending-cap-enforced-in-two-layers)); free services kept: edge-tts, RSS, Open-Meteo |
| Free DuckDuckGo search | Changed | Unreliable when measured; Claude's search tool with a daily limit ([ADR-034](DECISIONS.md#adr-034-web-search-through-claudes-own-search-tool)) |
| 8 GB of VRAM shared by Whisper and the LLM | Met | The LLM runs remotely; Whisper uses 1.1 GB ([ADR-043](DECISIONS.md#adr-043-whisper-in-int8_float16)) |
| Python 3.11+, current libraries, Windows | Met | Python 3.14 ([ADR-001](DECISIONS.md#adr-001-python-314)); versions checked at every phase |
| No cloned voices, no film quotes | Met | Stock neural and Piper voices; original lines in `i18n/locales`; the persona prompt forbids quoting films |

## Activation, speech and languages

| Requirement | Status | How | Tested in |
|---|---|---|---|
| Global push-to-talk hotkey | Met | Ctrl+Alt+J, Win32 `RegisterHotKey` ([ADR-011](DECISIONS.md#adr-011-tap-to-talk-with-a-win32-global-hotkey)) | `test_hotkey.py` |
| Offline, light wake word "Jarvis", or an alternative | Met | "Ei Jarvis" / "Hey Jarvis", openWakeWord confirmed by Whisper; about 2% of one core ([ADR-040](DECISIONS.md#adr-040-wake-word-ei-jarvis--hey-jarvis-with-openwakeword-confirmed-by-whisper)) | `test_wake.py`, `test_text.py` |
| Short sounds when listening starts and ends | Met | `audio/tones.py` | `test_pipeline.py` |
| Local Whisper on the GPU, detection restricted to pt/en | Met | faster-whisper large-v3-turbo ([ADR-015](DECISIONS.md#adr-015-whisper-large-v3-turbo-in-float16), [ADR-016](DECISIONS.md#adr-016-language-detection-restricted-to-portuguese-and-english)) | `test_language_choice.py` |
| Language detection errors on short phrases | Met | Confidence thresholds, stricter for short audio; otherwise the previous language | `test_language_choice.py` |
| End of speech by VAD, not a fixed time | Met | Silero VAD plus a loudness gate ([ADR-013](DECISIONS.md#adr-013-silero-vad-streamed-frame-by-frame-for-end-of-speech-detection), [ADR-018](DECISIONS.md#adr-018-loudness-gate-on-top-of-the-vad)) | `test_vad.py`, `test_listener.py` |
| Reply in the language spoken; voice commands lock it | Met | [ADR-033](DECISIONS.md#adr-033-language-lock-applies-to-replies-only) | `test_router.py`, `test_storage.py` |
| Every command in both languages; texts in i18n files | Met | Rules per language; `pt-BR.toml` and `en.toml` | `test_router.py`, `test_i18n.py` |

## Voice and personality

| Requirement | Status | How | Tested in |
|---|---|---|---|
| British male voice in English, Brazilian male voice in Portuguese | Met | edge-tts Ryan and Antonio; samples, including multilingual voices, offered in Phase 1 | — |
| Free online engine with an offline fallback, pluggable | Met | edge-tts, Piper fallback, phrase cache ([ADR-017](DECISIONS.md#adr-017-edge-tts-with-piper-as-offline-fallback-and-a-phrase-cache)) | `test_tts.py` |
| Interrupt the speech with the hotkey or the wake word | Met | [ADR-041](DECISIONS.md#adr-041-barge-in) | `test_pipeline.py` |
| Formal, polite, dry British wit; "sir" / "Mr. Camprubi" | Met | Persona prompt and locale texts | `test_persona.py` |
| Short spoken replies, details on the HUD | Met | 1–2 sentences, except news, searches and the briefing | `test_hud.py` |
| Errors in character | Met | Every failure has a spoken text (`errors.*`, `weather.unavailable`…) | `test_pipeline.py` |
| Greeting by time of day | Met | `startup.*`, `briefing.greeting.*` | `test_pipeline.py`, `test_briefing.py` |

## Brain

| Requirement | Status | How | Tested in |
|---|---|---|---|
| Local LLM through Ollama, Claude ready but off | Changed | Claude Haiku 5.5 is the provider; the `LLMProvider` interface keeps Ollama possible (V2 idea) | `test_claude.py` |
| Hybrid routing: rules first, LLM for the rest | Met | [ADR-019](DECISIONS.md#adr-019-rule-router-with-regular-expressions-per-language), [ADR-026](DECISIONS.md#adr-026-claude-through-the-official-sdk-with-our-own-tool-use-loop) | `test_router.py`, `test_brain.py` |
| Short conversation memory ("abre o segundo", "e amanhã?") | Met | [ADR-028](DECISIONS.md#adr-028-text-only-short-term-memory) | `test_memory_budget.py`, `test_files.py` |

## Tools

| # | Requirement | Status | How | Tested in |
|---|---|---|---|---|
| 1 | Open apps from the Start menu, aliases, fuzzy names | Met | [ADR-021](DECISIONS.md#adr-021-app-index-from-the-start-menu-get-startapps) | `test_tools.py` |
| 2 | Favourite sites and spoken domains | Met | `tools/sites.py` | `test_tools.py`, `test_router.py` |
| 3 | File search in configured folders, 5 results on the HUD, pick by voice | Met | [ADR-031](DECISIONS.md#adr-031-in-memory-file-index); programs are only revealed | `test_files.py`, `test_hud.py` |
| 4 | PC performance: CPU, RAM, GPU, disk; summary spoken, full on the HUD | Met | [ADR-023](DECISIONS.md#adr-023-psutil-and-nvml-for-pc-performance) | `test_tools.py`, `test_windows.py` |
| 5 | Media keys (Spotify Free) and volume | Met | [ADR-022](DECISIONS.md#adr-022-pycaw-for-volume-simulated-media-keys-for-playback) | `test_tools.py` |
| 6 | Lock the PC | Met | `tools/lock.py` | `test_tools.py` |
| 7 | Shut down, restart, close programs: spoken confirmation, timeout cancels | Met | [ADR-024](DECISIONS.md#adr-024-closing-programs-gracefully), [ADR-025](DECISIONS.md#adr-025-spoken-confirmation-for-dangerous-actions) | `test_pipeline.py` |
| 8 | Reminders: relative and absolute times, persisted, overdue ones announced, list and cancel | Met | [ADR-029](DECISIONS.md#adr-029-sqlite-through-the-standard-library), [ADR-030](DECISIONS.md#adr-030-our-own-bilingual-parser-for-reminder-times) | `test_reminders.py`, `test_when.py` |
| 9 | Weather: default or spoken city; now, today, tomorrow | Met | [ADR-032](DECISIONS.md#adr-032-open-meteo-through-httpx2) | `test_weather.py` |
| 10 | Tech news: RSS and Google News, last 24 h, no duplicates, 3–5 spoken, all linked on the HUD, translated | Met | [ADR-035](DECISIONS.md#adr-035-news-from-rss-chosen-and-summarised-by-claude) | `test_news.py`, `test_digest.py` |
| 11 | Web search with sources; failures in character | Changed | Claude's search tool ([ADR-034](DECISIONS.md#adr-034-web-search-through-claudes-own-search-tool)) | `test_claude.py`, `test_brain.py` |
| 12 | Morning briefing | Met | [ADR-036](DECISIONS.md#adr-036-morning-briefing-assembled-locally) | `test_briefing.py` |

## Security

| Requirement | Status | How | Tested in |
|---|---|---|---|
| The LLM calls registered tools only | Met | [ADR-020](DECISIONS.md#adr-020-explicit-tool-list-as-the-allowlist) | `test_brain.py` |
| No shell or code tool; nothing deletes files | Met | No such tool exists; files found are never run | `test_files.py` |
| Web content is data, never instructions | Met | Persona and bulletin prompts; HTML-escaped titles on the HUD; only http(s) links open | `test_hud.py`, `test_digest.py` |
| Answers only from what was fetched; "not found" otherwise | Met | Search and bulletin prompts; verified with real searches (Phase 4) | `test_digest.py` |
| Secrets only in `.env`, with `.env.example` | Met | [ADR-005](DECISIONS.md#adr-005-toml-configuration-validated-by-pydantic-secrets-in-env) | `test_config.py`, `test_doctor.py` |

## HUD

| Requirement | Status | How | Tested in |
|---|---|---|---|
| Floating, always on top, translucent, draggable, cyan, animated reactor | Met | [ADR-037](DECISIONS.md#adr-037-pyside6-essentials-for-the-hud), [ADR-038](DECISIONS.md#adr-038-hud-drawn-with-qpainter), [ADR-039](DECISIONS.md#adr-039-a-compact-hud-panel) | `test_hud.py` |
| States: idle, listening, thinking, speaking | Met | Reactor colour and pace, state label | `test_hud.py` |
| Shows what was heard, the reply, CPU/GPU/RAM, language, clickable lists | Met | Plus VRAM and API spending | `test_hud.py` |
| Never takes the focus; tray icon to show, hide and quit | Met | Measured on the real desktop (Phase 5) | `test_hud.py` |
| Never freezes | Met | Events cross threads through a queued Qt signal ([ADR-004](DECISIONS.md#adr-004-concurrency-asyncio-core-worker-threads-qt-on-the-main-thread)) | `test_hud.py` |
| Speaker verification later, with an extension point | Met | `core/verification.py`: `SpeakerVerifier`, `AcceptEveryone` | `test_pipeline.py` |

## Engineering

| Requirement | Status | How |
|---|---|---|
| Modular architecture | Met | One package per concern ([ADR-003](DECISIONS.md#adr-003-src-layout-one-package-per-component)) |
| Tool registry: a new tool never touches the core | Met | A module plus one line in `tools/__init__.py` |
| Concurrent pipeline that never blocks the HUD | Met | [ADR-004](DECISIONS.md#adr-004-concurrency-asyncio-core-worker-threads-qt-on-the-main-thread) |
| Configuration file plus `.env` | Met | TOML validated by pydantic ([ADR-005](DECISIONS.md#adr-005-toml-configuration-validated-by-pydantic-secrets-in-env)) |
| Leveled logs in local files; transcripts local, can be switched off | Met | `logs/jarvis.log`, `logs/transcripts.log`, `[logging] log_transcripts` ([ADR-007](DECISIONS.md#adr-007-standard-library-logging)) |
| Tests for the router, the reminder parser and the tools, with mocks | Met | 557 tests; fakes for audio, network, LLM and Windows |
| Type hints, linter, formatter | Met | mypy strict, ruff ([ADR-006](DECISIONS.md#adr-006-quality-tooling-ruff-mypy-strict-pytest-and-github-actions)) |
| Local commands within about 1.5 s, LLM within about 4 s; measured and reported | Met, with one exception | About 1.0–1.8 s locally and 2.5–3.5 s with Claude; a web search takes 5–6 s because the search itself takes 4–5 s (see the README) |
| Low CPU at rest, wake word included | Met | About 2% of one core; the HUD 0% |
| Simple installation, automatic checks, one command to run | Met | `uv sync`, `uv run jarvis --check`, `uv run jarvis`; a fresh clone verified before the release |
| Git from the start, public repository, Conventional Commits, MIT | Met | [ADR-008](DECISIONS.md#adr-008-public-github-repository-created-with-the-github-cli) |
