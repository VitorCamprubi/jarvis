# Ideas for v2

The v1 scope is frozen. Ideas that come up during v1 are recorded here and not implemented.

| Idea | Origin | Notes |
|---|---|---|
| Speaker verification: obey only the owner's voice | Original brief | v1 leaves an extension point in the `core` pipeline |
| Local LLM fallback through Ollama (offline or out of budget) | ADR-009 | Plugs in behind the `LLMProvider` interface |
| Play a specific song or playlist ("toca Despacito") | Phase 2 | Needs the Spotify Web API; v1 only drives the media keys |
| Force-close a program that ignores the close request | ADR-024 | A second confirmation, then terminate the process |
| City aliases for weather ("Nova York") | Phase 3 | Open-Meteo knows "Nova Iorque" and "New York" only; a `[weather.aliases]` table like the app aliases |
| Open a news story by voice ("abre a segunda notícia") | Phase 4 | v1 lists the links in the log and, from Phase 5, in the HUD |
| Speak while Claude is still writing (streamed answer) | ADR-042 | About 0.5–1.5 s less on long answers; complicates the tool-use loop |
| Speech recognition on the CPU when a game saturates the GPU | ADR-043 | A second, smaller Whisper model; only if int8_float16 is not enough |
| A single-word "Jarvis" wake word trained with Brazilian voices | ADR-040 | openWakeWord training notebook; v1 needs "Ei/Hey Jarvis" |
