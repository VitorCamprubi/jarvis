"""Normalise transcribed speech so rules can match it.

"Jarvis, abre o Spotify, por favor!" -> "abre o spotify"
"""

import re
import unicodedata

WAKE_WORDS = ("hey jarvis", "ei jarvis", "oi jarvis", "ok jarvis", "jarvis")
POLITENESS = ("por favor", "por gentileza", "please")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize(text: str) -> str:
    """Lowercase, no accents, no punctuation (except % and dots inside words), single spaces,
    without a leading "Jarvis" or politeness words."""
    # Apostrophes join words ("what's" -> "whats"), the plain and the typographic (U+2019).
    text = strip_accents(text.lower()).replace("'", "").replace(chr(0x2019), "")
    text = re.sub(r"[^a-z0-9%.\s]", " ", text)
    text = re.sub(r"(?<![a-z0-9])\.|\.(?![a-z0-9])", " ", text)  # keep "youtube.com", "2.5"
    text = " ".join(text.split())
    for wake_word in WAKE_WORDS:
        if text == wake_word or text.startswith(f"{wake_word} "):
            text = text[len(wake_word) :]
            break
    for phrase in POLITENESS:
        text = re.sub(rf"(?:^| ){phrase}(?= |$)", " ", text)
    return " ".join(text.split())
