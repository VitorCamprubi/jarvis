# Architecture

Target architecture of JARVIS v1, built phase by phase. Packages that are still empty
only carry a docstring describing their future responsibility.

## Components

| Package | Responsibility | Since |
|---|---|---|
| `jarvis.app` | Composition root: builds the components and wires them together | Phase 0 |
| `jarvis.config` | Layered TOML configuration and secrets | Phase 0 |
| `jarvis.core` | Core event loop thread, conversation pipeline, states, speaker-verification hook | Phase 1 |
| `jarvis.activation` | Global hotkey (Win32 `RegisterHotKey`); wake word in Phase 6 | Phase 1 |
| `jarvis.audio` | Microphone capture, Silero VAD + loudness gate, feedback tones, playback | Phase 1 |
| `jarvis.stt` | faster-whisper on CUDA, language restricted to pt/en | Phase 1 |
| `jarvis.tts` | edge-tts with phrase cache, Piper as offline fallback | Phase 1 |
| `jarvis.i18n` | pt-BR and en texts loaded from locale files | Phase 1 |
| `jarvis.router` | Bilingual rule-based router; unresolved requests go to the LLM | Phase 2 |
| `jarvis.tools` | Tool registry (allowlist) and one module per tool | Phase 2 |
| `jarvis.brain` | Claude provider, persona, short conversation memory | Phase 3 |
| `jarvis.storage` | SQLite persistence (reminders, API spending) | Phase 3 |
| `jarvis.hud` | PySide6 heads-up display and tray icon | Phase 5 |

Each pluggable component is a `typing.Protocol` (`Listener`, `SpeechToText`,
`TextToSpeech`, `Player`, `SpeakerVerifier`), so tests replace them with simple fakes
and later phases can swap implementations without touching the pipeline.

## Request flow

```mermaid
flowchart LR
    A[Hotkey / wake word] --> B[Record until silence]
    B --> C[Whisper STT]
    C --> D{Rule router}
    D -- simple command --> F[Tool]
    D -- anything else --> E[LLM with tool calling]
    E --> F
    F --> G[Short spoken reply]
    F --> H[Details on the HUD]
```

## One conversation turn (Phase 1)

```mermaid
sequenceDiagram
    participant K as Hotkey thread
    participant L as Core loop (asyncio)
    participant M as Microphone (PortAudio thread)
    participant W as Worker threads
    K->>L: call_soon(pipeline.activate)
    L->>L: start tone, state LISTENING
    M-->>L: 32 ms frames (call_soon_threadsafe)
    L->>L: Silero VAD + loudness gate per frame
    L->>W: stop tone (sd.wait) and Whisper, in parallel
    W-->>L: transcript (pt/en)
    L->>L: edge-tts (async) or Piper (worker) reply
    L->>W: play reply, state SPEAKING, then IDLE
```

## Threads

See [ADR-004](DECISIONS.md#adr-004-concurrency-asyncio-core-worker-threads-qt-on-the-main-thread).

```mermaid
flowchart TB
    subgraph main["Main thread"]
        HUD["Console now; Qt event loop (HUD, tray) from Phase 5"]
    end
    subgraph core["Core thread"]
        LOOP["asyncio loop: pipeline, VAD, HTTP, timers"]
    end
    subgraph pool["Worker threads"]
        W["Whisper on GPU, Piper, playback waits"]
    end
    HK["Hotkey thread (Win32 message loop)"] -- call_soon --> LOOP
    MIC["PortAudio callback thread"] -- audio frames --> LOOP
    LOOP -- "asyncio.to_thread" --> W
    LOOP -. "Qt signals (Phase 5)" .-> HUD
```
