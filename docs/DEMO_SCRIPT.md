# Demo video script (60–90 s)

Portuguese, with an English part that shows the bilingual design, and English subtitles for
LinkedIn ([ADR-048](DECISIONS.md#adr-048-the-demo-video-in-portuguese-with-an-english-part)).
JARVIS's replies vary a little (some phrases have variants and Claude words its own answers),
so the reply column shows what to expect, not exact text.

## Before recording

- Close notifications (Focus assist on), use a clean desktop, and keep the HUD in its corner.
- Ask something with Claude once beforehand: the first request of a session is a little
  slower, and the news feeds load in the background on start-up.
- Record with [OBS Studio](https://obsproject.com/) at 1080p, capturing the desktop, the
  microphone and the desktop audio (JARVIS's voice) on separate tracks, so their levels can
  be balanced later.
- Speak clearly and wait for the start tone the first time; after that, the request can follow
  "Ei Jarvis" in the same breath.

## Shots

| Time | On screen | You say | JARVIS (about) | English subtitle |
|---|---|---|---|---|
| 0:00–0:05 | Title over the desktop, HUD at rest: **J.A.R.V.I.S. — a voice assistant for Windows, in Portuguese and English** | — | — | — |
| 0:05–0:14 | HUD turns to LISTENING, then SPEAKING; Spotify opens | "Ei Jarvis, abre o Spotify." | "Abrindo Spotify, senhor." | "Hey Jarvis, open Spotify." / "Opening Spotify, sir." |
| 0:14–0:20 | Music starts, the volume changes | "Ei Jarvis, toca a música e coloca o volume em 30." *(or two requests)* | "Volume em 30 por cento, senhor." | "Play the music and set the volume to 30." |
| 0:20–0:36 | The bulletin starts; the HUD lists the stories with links | "Ei Jarvis, quais são as notícias de hoje?" | "Senhor, eis as principais notícias de tecnologia…" | "Hey Jarvis, what's today's news?" / "Sir, here are today's main tech stories…" |
| 0:36–0:42 | Cut in mid-bulletin: the voice stops at once; click a story, the browser opens it | "Ei Jarvis…" *(interrupting)* "obrigado, já basta." | "Às suas ordens, senhor." | "Hey Jarvis… thanks, that's enough." |
| 0:42–0:54 | The HUD labels switch to English | "Hey Jarvis, speak English." Then: "Hey Jarvis, will it rain tomorrow?" | "Certainly, sir…" / "Tomorrow in Sorocaba: …" | — |
| 0:54–1:06 | THINKING (amber), then the answer, sources listed on the HUD | "Hey Jarvis, search the web for the latest Python release." | "The latest stable release is Python …" | — |
| 1:06–1:16 | The safety net | "Hey Jarvis, shut down the computer." … "No." | "You'd like me to shut down the computer. Shall I proceed, sir?" … "Very well, sir. I'll leave it." | — |
| 1:16–1:25 | Closing card: **Python 3.14 · faster-whisper · Claude Haiku · PySide6 · github.com/VitorCamprubi/jarvis** | "Ei Jarvis, fala em português." | "Pois não, senhor…" | "Hey Jarvis, back to Portuguese." |

Optional, if there is time: "Bom dia, Jarvis" for the morning briefing, or "Me lembra em um
minuto de alongar" and let the reminder go off on camera.

## Editing

- Keep the cuts tight: remove the pauses before JARVIS answers only where they are long, and
  say so in the post ("edited for length") to stay honest about latency.
- Burn the English subtitles in (LinkedIn autoplays videos muted).
- Export 1080p MP4, under 90 s.

## Recording the README's GIF

The README shows a GIF rendered from the HUD's code
([ADR-047](DECISIONS.md#adr-047-a-demo-gif-rendered-by-the-huds-own-code-then-a-real-recording));
a real recording replaces it:

1. Install [ScreenToGif](https://www.screentogif.com/) (free, open source).
2. Record a region around the HUD (about 520 × 480 pixels) at 15 frames per second, for 10
   to 15 seconds: "Ei Jarvis, quais são as notícias de hoje?", and the list appearing.
3. Save as GIF, under about 5 MB, to `docs/media/hud-demo.gif`, and change the caption under
   the GIF in both READMEs.
