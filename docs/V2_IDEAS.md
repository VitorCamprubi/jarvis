# Ideas for v2

The v1 scope is frozen. Ideas that come up during v1 are recorded here and not implemented.

| Idea | Origin | Notes |
|---|---|---|
| Speaker verification: obey only the owner's voice | Original brief | v1 leaves an extension point in the `core` pipeline |
| Local LLM fallback through Ollama (offline or out of budget) | ADR-009 | Plugs in behind the `LLMProvider` interface |
| Play a specific song or playlist ("toca Despacito") | Phase 2 | Needs the Spotify Web API; v1 only drives the media keys |
| Force-close a program that ignores the close request | ADR-024 | A second confirmation, then terminate the process |
