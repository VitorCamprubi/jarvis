# Architecture Decision Records

Short ADRs: context, options considered, decision and reason. Newest at the bottom.
A decision is never edited after the fact; a later ADR supersedes it instead.

---

## ADR-001: Python 3.14

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The project needs a stable Python with Windows wheels for its native
  dependencies (CTranslate2 for faster-whisper, PySide6, onnxruntime, Piper).
- **Options:**
  - **A) 3.14 (3.14.8):** one year of maturity, bug fixes until Oct 2027; Windows wheels
    confirmed for CTranslate2 4.8.2, PySide6 6.12 and piper-tts 1.8 (abi3).
  - **B) 3.13 (3.13.16):** widest compatibility, but leaving its bug-fix period.
  - **C) 3.15.0:** released on 2026-10-09; CTranslate2 has no wheel for it yet, so
    faster-whisper cannot be installed.
- **Decision:** A. Pinned in `.python-version` and `requires-python = ">=3.14,<3.15"`.
- **Reason:** Latest version with every critical wheel available. uv downloads the
  interpreter automatically; falling back to 3.13 is a one-line change.

## ADR-002: uv as package and environment manager

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Installation must be simple and reproducible, ideally one command to run.
- **Options:**
  - **A) uv:** dependency resolution, lockfile (`uv.lock`), virtual environment and Python
    installation in one fast tool. Younger tool (0.x).
  - **B) Poetry:** mature, has a lockfile; slower and does not install Python.
  - **C) pip + venv + requirements.txt:** standard, but no real lockfile and a manual,
    fragile setup.
- **Decision:** A.
- **Reason:** Reproducible installs and `uv run jarvis` as the single command to run.
  Roughly Maven + Maven Wrapper + SDKMAN in one binary.

## ADR-003: `src` layout, one package per component

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The code must stay modular, with clear responsibilities and pluggable
  implementations (LLM, TTS, STT, activation).
- **Options:**
  - **A) `src/jarvis/` with one subpackage per component** (`core`, `activation`, `audio`,
    `stt`, `tts`, `brain`, `router`, `tools`, `storage`, `hud`, `config`, `i18n`), each
    pluggable component defining a `typing.Protocol` interface.
  - **B) Flat layout** (`jarvis/` at the root): one level less, but tests may import the
    working directory instead of the installed package and hide packaging errors.
  - **C) Hexagonal** (domain / application / adapters): too much ceremony for this size.
- **Decision:** A.
- **Reason:** Standard modern layout, maps one-to-one to the product's components, and
  keeps the composition in a single place (`app.py`). See [ARCHITECTURE.md](ARCHITECTURE.md).

## ADR-004: Concurrency: asyncio core, worker threads, Qt on the main thread

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The assistant listens, transcribes, calls the network, speaks and updates
  the HUD at the same time, and the HUD must never freeze. Speech must be interruptible
  and confirmations must time out.
- **Options:**
  - **A) Hybrid:** an asyncio event loop in a dedicated "core" thread (pipeline, router,
    tools, HTTP, timers); blocking work (Whisper on the GPU, Piper, Win32 calls) goes
    to a thread pool via `asyncio.to_thread`; Qt keeps the main thread and talks to the
    core through thread-safe Qt signals.
  - **B) Threads and queues only:** familiar (`ExecutorService` + `BlockingQueue`), but
    cancellation and timeouts are hand-rolled and races are more likely.
  - **C) A single asyncio loop inside Qt** (qasync / QtAsyncio): no bridge, but any
    accidental blocking call freezes the HUD.
- **Decision:** A.
- **Reason:** Built-in cancellation (`task.cancel()` interrupts speech) and timeouts
  (`asyncio.wait_for` for "Shall I proceed, sir?"), cheap concurrent I/O (many RSS feeds
  at once), and the HUD thread never runs heavy work. The GIL is not a bottleneck here:
  CTranslate2, PortAudio and onnxruntime release it while working.

## ADR-005: TOML configuration validated by pydantic, secrets in .env

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Configuration must live in files, with secrets kept out of Git.
- **Options:**
  - **A) TOML + pydantic + .env:** reader in the standard library (`tomllib`), explicit
    types, same format as `pyproject.toml`.
  - **B) YAML + pydantic + .env:** familiar from Spring's `application.yml`, but implicit
    conversions are a trap (`no` becomes `false`, dangerous in yes/no word lists).
- **Decision:** A, in three layers: `config/default.toml` (versioned, the only place
  defaults live), `config/local.toml` (personal overrides, git-ignored, merged key by key)
  and `.env` (secrets only, read with pydantic-settings as `SecretStr`). Unknown keys are
  rejected so typos fail loudly. Locale files will use TOML too.
- **Reason:** No implicit type surprises, no extra parser dependency, typed and validated
  access (similar to Spring's `@ConfigurationProperties` + Bean Validation).

## ADR-006: Quality tooling: ruff, mypy (strict), pytest and GitHub Actions

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Code quality matters as much as features (portfolio project).
- **Options:**
  - **A) ruff (lint + format) + mypy strict + pytest, run by GitHub Actions on Windows**
    for every push and pull request.
  - **B) Same tools without CI.**
  - **C) pyright instead of mypy:** faster, but less of a reference in the ecosystem.
- **Decision:** A.
- **Reason:** One fast tool for lint and format, the reference type checker in strict
  mode, and CI that proves the checks pass on the target OS.

## ADR-007: Standard library logging

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Logs need levels, local files and a separate, optional transcript log.
- **Options:**
  - **A) `logging` from the standard library** with `RotatingFileHandler`.
  - **B) loguru:** simpler API, one more dependency.
- **Decision:** A. `logs/jarvis.log` for application events (third-party loggers at
  WARNING), `logs/transcripts.log` for what the user said, never propagated to other
  handlers and switched off with `logging.log_transcripts = false`.
- **Reason:** Zero dependencies and the standard every library already logs to
  (comparable to SLF4J + Logback).

## ADR-008: Public GitHub repository created with the GitHub CLI

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The project lives in a public repository on GitHub (VitorCamprubi/jarvis).
- **Options:**
  - **A) GitHub CLI (`gh`):** the owner authenticates once with `gh auth login`; the
    repository is created and pushed from the command line. Also useful for CI and releases.
  - **B) Create the empty repository on github.com** and add the remote manually.
- **Decision:** A.
- **Reason:** Scriptable and reusable for later phases (CI status, releases).

## ADR-009: Claude API (Haiku 5.5) as the only LLM provider in v1

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The original brief asked for a local LLM through Ollama (zero cost), with a
  Claude provider implemented but disabled. The owner decided to use the paid Claude API
  instead, with a total budget of US$ 5 (see ADR-010).
- **Options:**
  - **A) Claude Haiku 5.5 as main brain, Ollama as fallback:** never without an LLM, but
    requires Ollama plus a ~5 GB model, shares VRAM with Whisper and doubles provider testing.
  - **B) Claude Haiku 5.5 only, behind the `LLMProvider` interface:** simplest install and
    the whole GPU is left to speech recognition; without internet or budget, only the local
    rule-based commands work.
  - **C) Claude Sonnet 5.5:** more capable, but about 20 times the price of Haiku.
- **Decision:** B, model `claude-haiku-5-5`. Without internet or budget, JARVIS keeps
  answering the commands handled by local rules and explains the limitation in character.
  An Ollama fallback is listed in [V2_IDEAS.md](V2_IDEAS.md).
- **Reason:** Better tool calling and Portuguese than a local 7–8B model, one less runtime
  to install, and about 6.8 GB of free VRAM left for Whisper (larger, more accurate model).
  At US$ 0.10 / 0.50 per million input / output tokens, a tool-using request is estimated
  at US$ 0.001–0.002, so US$ 5 covers roughly 2,500–5,000 LLM requests; rule-based
  commands cost nothing. Real costs will be measured in Phase 3.
- **Consequences:** Conversation and tool selection need an internet connection. The
  "zero cost" constraint now has one paid exception, capped at US$ 5.

## ADR-010: US$ 5 spending cap enforced in two layers

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Total Claude API spending must never exceed US$ 5.
- **Options:**
  - **A) Server-side only:** prepaid credits with auto-reload disabled and a workspace
    spend limit in the Anthropic Console. A hard guarantee, but requests simply start
    failing when the money runs out.
  - **B) Local guard only:** the app prices every response from its token usage and stops
    before the cap. Graceful and visible, but an estimate, not a guarantee.
  - **C) Both.**
- **Decision:** C.
  - **Server (done by the owner in the Console):** at most US$ 5 of prepaid credits,
    auto-reload disabled, workspace spend limit set.
  - **Local (Phase 3):** each response's token usage is priced with rates from the
    configuration and accumulated in SQLite; a warning at US$ 4.00 and a hard stop at
    US$ 4.90, after which JARVIS switches to rules-only mode and says so in character.
    Spending is shown by `jarvis --check` and on the HUD.
- **Reason:** The server limit is the guarantee; the local guard avoids hitting it
  mid-sentence and makes spending visible.

## ADR-011: Tap-to-talk with a Win32 global hotkey

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Phases 1–5 are activated by a global keyboard shortcut; the wake word
  arrives in Phase 6 and should use the same flow.
- **Options:**
  - **A) Tap to talk:** one press starts listening, voice activity detection ends it.
    Implemented with the Win32 `RegisterHotKey` API through `ctypes`.
  - **B) Hold to talk with pynput:** precise control, but needs a low-level keyboard hook
    that sees every key (Windows silently drops slow hooks), and makes the VAD useless.
  - **C) Both modes:** more code for little gain. (`keyboard` was excluded: unmaintained
    since 2020.)
- **Decision:** A, default shortcut `Ctrl+Alt+J` (configurable). A second press while
  listening cancels; listening also stops after 5 s without speech or 15 s in total.
- **Reason:** Same flow as the future wake word, no dependency, no keyboard hook and no
  CPU use while idle: Windows only notifies the registered combination.

## ADR-012: sounddevice and soundfile for audio I/O

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** The microphone must be read in small blocks and replies played back,
  including the MP3 produced by edge-tts.
- **Options:** **A) sounddevice (PortAudio) + soundfile** (decodes MP3; measured: 2 ms for
  a 4.6 s reply); **B) PyAudio** (older API, no numpy integration); **C) miniaudio**
  (all-in-one, much less used).
- **Decision:** A. Input and output devices are selectable by part of their name, because
  the Windows default output on the owner's PC is not the headset.
- **Reason:** Both libraries are maintained, numpy-native and ship their native libraries
  in Windows wheels.

## ADR-013: Silero VAD, streamed frame by frame, for end-of-speech detection

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Recording must stop when the user stops talking, not after a fixed time.
- **Options:**
  - **A) Silero VAD v6:** small neural network; the ONNX model already ships with
    faster-whisper. A thin wrapper feeds it 32 ms frames, carrying its LSTM state.
  - **B) webrtcvad:** very light, but more false positives with noise and breathing.
  - **C) Energy threshold:** simplest and most fragile (fans, keyboard).
- **Decision:** A, with a 600 ms silence window (configurable).
- **Reason:** Best accuracy at negligible CPU cost and no extra dependency. The model file
  is internal to faster-whisper, so its version is pinned by the lockfile and a test runs it.

## ADR-014: CUDA libraries from NVIDIA's pip wheels

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** CTranslate2 (behind faster-whisper) needs cuBLAS 12 and cuDNN 9 on the GPU;
  its Windows wheel does not ship them (`cublas64_12.dll is not found`).
- **Options:**
  - **A) `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` wheels** (~1.3 GB download), with the
    app registering their DLL folders at start-up. Tested on the target PC.
  - **B) System-wide CUDA Toolkit + cuDNN:** manual, 3+ GB, needs admin rights.
  - **C) Third-party archive suggested by faster-whisper's README:** manual download.
- **Decision:** A, in a `cuda` dependency group installed by default; CI skips it.
- **Reason:** `uv sync` installs everything; no manual or admin steps.

## ADR-015: Whisper large-v3-turbo in float16

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Speech recognition must be fast (target ~1.5 s per local command) and good
  in Brazilian Portuguese. Measured on the RTX 4060 Ti with six short pt/en commands:

  | Model | Auto language, beam 5 | Forced language, greedy | VRAM | Correct |
  |---|---|---|---|---|
  | large-v3-turbo float16 | 0.35–0.42 s | 0.18–0.20 s | 2.2 GB | 6/6 |
  | large-v3-turbo int8_float16 | 0.33–0.38 s | 0.17–0.20 s | 1.1 GB | 6/6 |
  | large-v3 float16 | 0.45–0.67 s | 0.27–0.40 s | 3.9 GB | 6/6 |

- **Options:** A) turbo float16; B) turbo int8_float16; C) large-v3 float16.
- **Decision:** A. Model and precision are configuration values.
- **Reason:** With no local LLM (ADR-009) VRAM is plentiful, so there is no reason to
  quantise; large-v3 costs ~0.2 s more for no measurable gain on these commands. To be
  re-checked with the owner's real voice.

## ADR-016: Language detection restricted to Portuguese and English

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Whisper's language detection is unreliable on short phrases and may pick a
  third language (Spanish, Galician) for Portuguese commands.
- **Options:**
  - **A) Restricted detection:** keep only the pt and en probabilities, renormalise and
    take the larger; when it is not confident enough (stricter for audio under 1.5 s),
    keep the language of the previous turn (initially the configured default).
  - **B) Transcribe twice** (forced pt and forced en) and keep the more confident result:
    more robust, ~0.2 s slower.
  - **C) Trust Whisper's detection as is.**
- **Decision:** A.
- **Reason:** No extra latency and handles the common failure; the previous turn's
  language is the best prior in a conversation.

## ADR-017: edge-tts with Piper as offline fallback and a phrase cache

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Replies are spoken with a British male voice in English and a Brazilian male
  voice in Portuguese. Measured: edge-tts takes 0.70 s to the first audio chunk and 1.1 s
  in total for a short reply; Piper takes 0.1 s on the CPU.
- **Options:**
  - **A) edge-tts primary, Piper fallback, disk cache of spoken phrases.**
  - **B) Piper primary:** fastest and always offline, but a more synthetic voice.
  - **C) edge-tts only:** silent without internet.
- **Decision:** A. Piper takes over when edge-tts fails or does not start answering within
  2 s, and edge-tts is skipped for a minute after a failure. Phrases already synthesised by
  edge-tts are replayed from `data/tts-cache`.
- **Reason:** Best voice quality with a guaranteed offline voice. edge-tts relies on an
  unofficial Microsoft endpoint that has changed before; Piper covers that risk. Piper is
  GPL-3.0: this project stays MIT because it uses, but does not redistribute, Piper.
  Voices used: CC0 (Brazilian) and CC-BY-SA / Mimic 3 (British).
- **Consequences:** A new phrase takes ~1.1 s to synthesise, so the 1.5 s target is met
  for cached phrases; streaming playback is a Phase 6 latency task. Only fixed phrases from
  the locale files are cached: replies containing what the user said are never written to
  disk, consistent with the option to switch off the transcript log.

## ADR-018: Loudness gate on top of the VAD

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Measured on the owner's PC with nobody speaking into the headset: the
  microphone level stayed around -58 dBFS, yet Silero rated almost half of the frames as
  speech (distant voices: a TV, a video, people nearby). A recording that starts this way
  only stops at the 15 s limit.
- **Options:**
  - **A) Loudness gate:** frames quieter than `vad.min_speech_level_dbfs` count as silence;
    `jarvis --mic-test` measures the background and the owner's voice and suggests a value.
  - **B) Higher VAD threshold:** does not help, distant speech scores above 0.9.
  - **C) Nothing:** occasional 15 s recordings in a noisy room.
- **Decision:** A, default -45 dBFS (-100 disables it).
- **Reason:** The headset microphone is close to the mouth, so the owner's voice is far
  louder than voices across the room; the gate filters them at no cost.

## ADR-019: Rule router with regular expressions per language

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Simple, fixed commands must be resolved locally (fast and free), in both
  languages, before anything reaches the LLM (Phase 3).
- **Options:**
  - **A) Regular expressions per intent and language** over normalised text (lowercase, no
    accents or punctuation), with named groups for arguments; fuzzy matching only for
    argument values such as app names.
  - **B) Fuzzy matching of the whole sentence** against example phrases: tolerant, but
    false positives are dangerous ("shut down") and arguments are hard to extract.
  - **C) Local intent classifier:** another model, more latency, less transparent.
- **Decision:** A. Each tool declares its own patterns; every pattern of both languages is
  tried, and the reply uses the language the user spoke.
- **Reason:** Predictable, sub-millisecond and testable with phrase tables; phrasings the
  rules miss will go to the LLM.

## ADR-020: Explicit tool list as the allowlist

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Tools must be self-contained modules, adding one must not touch the core,
  and the LLM may only call registered tools.
- **Options:**
  - **A) Explicit list in `jarvis/tools/__init__.py`:** each tool is a module with name,
    description, a pydantic parameter model (the JSON schema for Claude in Phase 3),
    router patterns and `run()`.
  - **B) Auto-discovery** with a decorator, like Spring's component scan: zero lines, but
    any module in the package silently becomes callable.
  - **C) Plugins through entry points:** built for third-party tools, overkill here.
- **Decision:** A.
- **Reason:** The list is the security allowlist, in one place and easy to audit; a new
  tool is one module plus one line, outside the core.

## ADR-021: App index from the Start menu (`Get-StartApps`)

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** "Open X" must find any app the user sees in the Start menu.
- **Options:**
  - **A) `Get-StartApps`:** 215 apps on the target PC in 0.8 s, including Store apps
    (WhatsApp); launched through `shell:AppsFolder`.
  - **B) Scan `.lnk` shortcuts** in the user and all-users Start menu folders (162):
    pure Python, but misses Store apps.
  - **C) Both, merged:** most coverage, duplicates to reconcile.
- **Decision:** A, loaded in the background at start-up and refreshed periodically, with
  rapidfuzz for approximate names and aliases in the configuration (an alias may point to a
  URL: "browser" opens the default browser, since Chrome is not installed).
- **Reason:** It is exactly the Start menu's own list, Store apps included.

## ADR-022: pycaw for volume, simulated media keys for playback

- **Date:** 2026-10-09 · **Status:** Accepted
- **Options:** **A) pycaw** (Windows Core Audio: set a percentage, read the level, mute)
  **plus media keys** (play/pause, next, previous; works with Spotify Free);
  **B) virtual volume keys only** (no "set to 30 %", 2 % steps); **C) nircmd** (third-party
  executable).
- **Decision:** A.
- **Reason:** Absolute volume control needs Core Audio; pycaw is pure Python and
  maintained (September 2026 release).

## ADR-023: psutil and NVML for PC performance

- **Date:** 2026-10-09 · **Status:** Accepted
- **Options:** **A) psutil** (CPU, RAM, disks) **plus nvidia-ml-py** (NVIDIA's official NVML
  bindings: GPU load, temperature, VRAM in 42 ms); **B) psutil plus parsing `nvidia-smi`**
  (slower, fragile); **C) CPU temperature through LibreHardwareMonitor** (driver and admin
  rights, not required by the scope).
- **Decision:** A. psutil has no CPU temperature on Windows; the scope asks for GPU
  temperature only.

## ADR-024: Closing programs gracefully

- **Date:** 2026-10-09 · **Status:** Accepted
- **Options:** **A) Ask the windows to close** (WM_CLOSE, like clicking X; the app may ask
  to save); **B) force-kill the process** (may lose unsaved work); **C) A, then offer to
  force it** after a second confirmation.
- **Decision:** A. Shell, system and JARVIS's own windows are never closed.
- **Reason:** No data loss, in line with the v1 rule that no tool destroys data.

## ADR-025: Spoken confirmation for dangerous actions

- **Date:** 2026-10-09 · **Status:** Accepted
- **Context:** Shutting down, restarting and closing programs require confirmation by voice
  (original brief).
- **Decision:** The tool returns a confirmation request; JARVIS asks ("Shall I proceed,
  sir?"), plays the listening tone and listens again without the hotkey for up to 6 s. Yes
  and no words are accepted in both languages; "no" wins over "yes", and silence or anything
  unclear cancels. Shutdown and restart run with a 5 s delay so the reply can finish.

## ADR-026: Claude through the official SDK with our own tool-use loop

- **Date:** 2026-10-12 · **Status:** Accepted
- **Context:** Requests the rules cannot resolve go to Claude Haiku 5.5 (ADR-009) with every
  registered tool available through tool calling.
- **Options:**
  - **A) Official `anthropic` SDK (async client) with our own loop:** before each request we
    check the budget, only allowlisted tools exist, dangerous tools still need a spoken
    "yes", and the number of iterations is capped.
  - **B) The SDK's Tool Runner (beta):** less code, but it executes tools by itself, which
    leaves no natural place for the voice confirmation or the spending cap.
  - **C) Raw HTTP:** re-implements the SDK.
- **Decision:** A, behind an `LLMProvider` interface (`ClaudeProvider` is its only
  implementation in v1).
- **Reason:** Safety and cost controls sit exactly where each request is made.

## ADR-027: Adaptive thinking at low effort

- **Date:** 2026-10-12 · **Status:** Accepted, confirmed by measurement (2026-10-13)
- **Context:** Voice replies must start within about 4 s when the LLM is involved.
- **Options:** **A) adaptive thinking, `effort: "low"`** (Anthropic's recommendation for chat
  and short tool tasks; the model may skip thinking on simple requests); **B) thinking
  disabled** (lowest latency, but the model may skip a tool it needs); **C) default
  `medium` effort** (better reasoning, slower and dearer).
- **Decision:** A. Effort is a configuration value; A and B will be measured with the real
  API key before the phase closes.
- **Measured (2026-10-13, Haiku 5.5, 6 requests each):** A and B both answer in 1.0–1.5 s
  per request and both called the right tools (reminder, weather); B gave terser
  follow-ups ("Em 1500, senhor."). Tools and the system prompt (2,916 tokens) are cached
  from the second request on. Twelve requests cost about US$ 0.0017. A stays.

## ADR-028: Text-only short-term memory

- **Date:** 2026-10-12 · **Status:** Accepted
- **Context:** Follow-ups such as "and tomorrow?" or "open the second one" need context.
  Claude Haiku 5.5 rejects replayed thinking blocks once earlier history changes, so a
  sliding window must not resend old reasoning.
- **Options:** **A) in-memory, text-only:** the last 6 exchanges (what was said, the reply,
  a one-line summary of tool actions), forgotten after 10 minutes of silence, plus the last
  result list kept apart so "open the second one" works through the rules; **B) persist
  the conversation in SQLite:** survives restarts, more personal data at rest; **C)
  server-side compaction or memory:** overkill.
- **Decision:** A.
- **Reason:** Append-only by construction, cheap in tokens and nothing personal on disk.

## ADR-029: SQLite through the standard library

- **Date:** 2026-10-12 · **Status:** Accepted
- **Options:** **A) `sqlite3` with small repository classes** (like JDBC plus DAOs), run on a
  worker thread, schema versioned in the database; **B) aiosqlite:** native async, one more
  dependency; **C) an ORM (SQLAlchemy):** overkill for three tables.
- **Decision:** A, in `data/jarvis.db`: reminders, API usage and settings (language lock).

## ADR-030: Our own bilingual parser for reminder times

- **Date:** 2026-10-12 · **Status:** Accepted
- **Options:**
  - **A) Own parser** (regular expressions and spoken numbers) for "em 20 minutos",
    "daqui a meia hora", "às 18h", "amanhã às 9h", "in 20 minutes", "at 6 pm",
    "tomorrow at 9"; unusual phrasings go to Claude, which computes the time (the prompt
    carries the current local time) and calls the tool with an ISO date-time.
  - **B) dateparser:** broad, but Portuguese forms such as "às 18h" or "daqui a" are not
    documented and results can surprise.
  - **C) Claude only:** costs API calls for every reminder and fails offline.
- **Decision:** A. Reminders are stored in SQLite; those that fell due while JARVIS was
  closed are announced at start-up; an announcement waits for a conversation in progress.

## ADR-031: In-memory file index

- **Date:** 2026-10-12 · **Status:** Accepted
- **Context:** On the owner's PC the Desktop alone holds 112,000 files, 104,000 of them in
  build, dependency or `.git` folders.
- **Options:** **A) in-memory index** of names under the configured folders, skipping build,
  dependency and VCS folders (about 10,000 files), rebuilt in the background every 10
  minutes; **B) walk the folders on every request:** always fresh, slow here; **C) query the
  Windows Search index:** fast and content-aware, but complex and dependent on indexer
  settings.
- **Decision:** A. Up to five results; "open the first/second..." chooses one. Executables
  and scripts are never run: JARVIS opens their folder with the file selected instead.

## ADR-032: Open-Meteo through httpx2

- **Date:** 2026-10-12 · **Status:** Accepted
- **Options:** **A) Open-Meteo forecast and geocoding APIs through `httpx2`** (async, already
  installed with the Anthropic SDK); **B) the same through `aiohttp`** (installed with
  edge-tts); **C) `urllib` on a worker thread.**
- **Decision:** A. Current conditions, today and tomorrow; a spoken city is geocoded,
  preferring Brazil.
- **Amended (2026-10-12, real tests):** "preferring Brazil" picked Tóquio (Pará) and Nova
  Iorque (Maranhão), and Open-Meteo matches names only in the language asked ("londres" in
  English is a village in Argentina). The city is now looked up in Portuguese and English
  in parallel and the most populous result wins; on a tie, the name in the reply language.

## ADR-033: Language lock applies to replies only

- **Date:** 2026-10-12 · **Status:** Accepted
- **Options:** **A) the lock fixes the reply language;** Whisper keeps detecting what is
  spoken, so Portuguese is still understood while English replies are locked; **B) the
  lock also forces Whisper's language:** ~0.2 s faster, but the other language would be
  transcribed as nonsense.
- **Decision:** A. "Jarvis, speak English" / "fala em português" lock, "auto language" /
  "volta ao automático" unlock; the lock is stored and survives restarts.

## ADR-034: Web search through Claude's own search tool

- **Date:** 2026-10-13 · **Status:** Accepted
- **Context:** The brief asked for free DuckDuckGo search. Measured on 2026-10-13: the
  `ddgs` library's DuckDuckGo backend was blocked after the first query, and its
  multi-engine fallback answered 3 of 6 queries in 3–4 s. Both scrape result pages, so they
  break whenever the sites change.
- **Options:** **A) Claude's server-side `web_search` tool** (official; results come with
  sources; measured 5.3 s and US$ 0.012 per search on Haiku 5.5); **B) `ddgs`** (free,
  unreliable as measured); **C) the free Wikipedia and DuckDuckGo Instant Answer APIs**
  (stable, but encyclopaedic topics only).
- **Decision:** A. At most 2 searches per question and 20 per day (configurable); each
  search adds US$ 0.01 to the local budget. The brain offers the tool only while today's
  limit lasts, answers only from the results and says when it found nothing. Sources are
  logged (and shown in the HUD from Phase 5).

## ADR-035: News from RSS, chosen and summarised by Claude

- **Date:** 2026-10-13 · **Status:** Accepted
- **Options:** **A) Claude picks and summarises:** feeds are fetched in parallel, kept to the
  last 24 h and de-duplicated by similar titles; only titles, sources and times go to the
  model, which picks the 3–5 main stories and tells them in the reply language (about
  US$ 0.001); **B) no LLM:** rank stories by how many sources carry them and read the
  titles; **C) Claude reads the full articles:** better summaries, about ten times the
  tokens and much slower.
- **Decision:** A, with B as the fallback when the LLM is offline, not configured or out of
  budget. Feeds are parsed with `feedparser` (6.0.14, tested on Python 3.14) and cached for
  15 minutes. Sources and Google News topics live in the configuration.

## ADR-036: Morning briefing assembled locally

- **Date:** 2026-10-13 · **Status:** Accepted
- **Options:** **A) a fixed running order assembled by JARVIS:** greeting, today's weather,
  today's reminders, then the three main stories from ADR-035; **B) one LLM call writes the
  whole briefing from the data:** more natural, less predictable, and fully dependent on
  the API.
- **Decision:** A. "Bom dia, Jarvis" / "Good morning, Jarvis" triggers it; weather and news
  are fetched in parallel, and each part fails gracefully on its own.

## ADR-037: PySide6-Essentials for the HUD

- **Date:** 2026-10-13 · **Status:** Accepted
- **Context:** The HUD is a frameless, semi-transparent, always-on-top window that never
  takes the focus, plus a tray icon; ADR-004 already puts Qt on the main thread.
- **Options:** **A) `PySide6-Essentials` 6.12** (official Qt for Python, LGPL, 78 MB:
  only QtCore, QtGui and QtWidgets); **B) PyQt6** (same API, GPL: the repository would have
  to leave MIT); **C) Tkinter + pystray** (no download, but no real translucency or smooth
  animation on Windows, and pystray is unmaintained since 2023).
- **Decision:** A. The full `PySide6` package would also pull in WebEngine and PDF.

## ADR-038: HUD drawn with QPainter

- **Date:** 2026-10-13 · **Status:** Accepted
- **Options:** **A) Qt widgets, with the reactor and gauges painted in code (QPainter)**;
  **B) Qt Quick / QML** (GPU-smooth, but a second language and a Python↔QML bridge, harder
  to test); **C) pre-rendered images or GIFs per state** (static, blurry when scaled).
- **Decision:** A. Everything stays in Python and can be rendered to an image in tests.
  The reactor animates at 30 fps only while listening, thinking or speaking; at rest it
  pulses slowly, keeping CPU use near zero.

## ADR-039: A compact HUD panel

- **Date:** 2026-10-13 · **Status:** Accepted
- **Options:** **A) a compact fixed panel** (about 380 × 300, top right, draggable, position
  remembered): reactor coloured by state, language, CPU/GPU/RAM, API spending, what was
  heard and the reply, plus an extra area for clickable lists and details that folds away
  after 60 s; **B) an orb at rest** that grows into the panel when active (less in the
  way, but two layouts and animated resizing); **C) a large panel** with the history of
  the last exchanges (takes a lot of screen).
- **Decision:** A. The tray icon shows, hides and quits; web links open in the browser and
  files open through the same safe path as voice (programs are only shown, never run).

## ADR-040: Wake word "Ei Jarvis" / "Hey Jarvis" with openWakeWord, confirmed by Whisper

- **Date:** 2026-10-15 · **Status:** Accepted
- **Context:** The brief asks for an offline, light "Jarvis" wake word, or an alternative
  phrase if the single word is unreliable. Measured with openWakeWord's pre-trained
  "hey jarvis" model on synthetic voices: English pronunciation scores 1.00, Brazilian
  pronunciation only 0.18–0.26 (the model fires at 0.5), look-alikes ("Jair", "Harvey",
  "jars") and ordinary sentences at most 0.01; 1.6 ms of CPU per 80 ms of audio. Whisper
  transcribed "Jarvis" correctly in every clip and never in the look-alikes.
- **Options:** **A) openWakeWord "hey jarvis", with Whisper confirming the uncertain scores**
  (free, offline, about 2% of one core; the package has had no release since 2024 but works
  on Python 3.14; its models are non-commercial, fine for personal use); **B) Porcupine's
  built-in "Jarvis"** (proprietary, needs a Picovoice account and an online-validated key,
  accent support unknown); **C) training a custom model** (hours of Colab work, uncertain).
- **Decision:** A. A score of 0.5 or more wakes JARVIS at once; between 0.1 and 0.5 the
  last seconds are transcribed and JARVIS wakes only if they contain "Jarvis". The last two
  seconds of audio are kept, so "Ei Jarvis, abre o Spotify" works in one breath.

## ADR-041: Barge-in

- **Date:** 2026-10-15 · **Status:** Accepted
- **Options:** **A) the hotkey or the wake word while JARVIS speaks stops the speech and
  starts listening at once;** **B) it only stops the speech.**
- **Decision:** A.

## ADR-042: Speaking sentence by sentence

- **Date:** 2026-10-15 · **Status:** Accepted
- **Context:** Long replies (news, briefing, LLM answers) wait for the whole text to be
  synthesised: 1–1.5 s before the first word.
- **Options:** **A) synthesise and play sentence by sentence,** the next sentence being
  synthesised while the current one plays; **B) A plus streaming the LLM's answer** into
  the speech; **C) as before.**
- **Decision:** A, plus fetching the news feeds in the background so a news request does
  not wait for them. B is recorded in V2_IDEAS.

## ADR-043: Whisper in int8_float16

- **Date:** 2026-10-15 · **Status:** Accepted
- **Context:** While a game runs, the GPU and its memory are busy and speech recognition
  took up to 4 s (Phase 1).
- **Options:** **A) `int8_float16`:** the same speed as float16 on this GPU (Phase 1
  measurement) in half the video memory, 1.1 GB instead of 2.2 GB; **B) A plus a CPU model
  when the GPU is saturated;** **C) keep float16** and suggest NVIDIA's maximum-performance
  setting.
- **Decision:** A, measured again with a game running; B goes to V2_IDEAS if needed.

## ADR-044: Start with Windows through the user's Run registry key

- **Date:** 2026-10-15 · **Status:** Accepted
- **Options:** **A) `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`,** switched by
  `jarvis --autostart on|off`; **B) a shortcut in the Startup folder;** **C) a scheduled
  task at logon.**
- **Decision:** A. JARVIS then starts with `pythonw` (no console): the HUD and tray are its
  interface, the log file records everything, and start-up errors show a Windows message
  box. Task Manager lists it under start-up apps, where it can also be disabled.

## ADR-045: The HUD steps aside for full-screen apps

- **Date:** 2026-10-15 · **Status:** Accepted
- **Options:** **A) hide the HUD automatically while a full-screen app (game, video,
  presentation) is in front,** using Windows' own notification state, and bring it back
  afterwards; **B) manual only,** from the tray.
- **Decision:** A. JARVIS keeps answering by voice while hidden.
