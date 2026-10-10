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
