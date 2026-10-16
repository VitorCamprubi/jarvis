"""Normalise transcribed speech so rules can match it.

"Jarvis, abre o Spotify, por favor!" -> "abre o spotify"
"""

import re
import unicodedata

from rapidfuzz import fuzz

WAKE_WORDS = ("hey jarvis", "ei jarvis", "oi jarvis", "ok jarvis", "jarvis")
POLITENESS = ("por favor", "por gentileza", "please")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def simplify(text: str) -> str:
    """Lowercase, no accents, no punctuation (except % and dots inside words), single spaces."""
    # Apostrophes join words ("what's" -> "whats"), the plain and the typographic (U+2019).
    text = strip_accents(text.lower()).replace("'", "").replace(chr(0x2019), "")
    text = re.sub(r"[^a-z0-9%.\s]", " ", text)
    text = re.sub(r"(?<![a-z0-9])\.|\.(?![a-z0-9])", " ", text)  # keep "youtube.com", "2.5"
    return " ".join(text.split())


def normalize(text: str) -> str:
    """simplify, then without a leading "Jarvis" or politeness words."""
    text = simplify(text)
    for wake_word in WAKE_WORDS:
        if text == wake_word or text.startswith(f"{wake_word} "):
            text = text[len(wake_word) :]
            break
    for phrase in POLITENESS:
        text = re.sub(rf"(?:^| ){phrase}(?= |$)", " ", text)
    return " ".join(text.split())


WAKE_NAME = "jarvis"
WAKE_NAME_SIMILARITY = 80  # Whisper may write "Jarvis", "Jarvis," or "Jarves"


WAKE_NAME_MIN_LETTERS = 5  # "jars" is close in letters, but too short to be the name


def _is_wake_name(word: str) -> bool:
    simple = simplify(word)
    return (
        len(simple) >= WAKE_NAME_MIN_LETTERS
        and fuzz.ratio(simple, WAKE_NAME) >= WAKE_NAME_SIMILARITY
    )


def mentions_wake_word(text: str) -> bool:
    """Does a transcription contain "Jarvis"? Used to confirm an uncertain wake word."""
    return any(_is_wake_name(word) for word in text.split())


def after_wake_word(text: str) -> str:
    """The request that follows "Ei Jarvis" in a transcription woken by voice ("Ei Jarvis,
    abre o Spotify" -> "abre o Spotify"). Whisper spells the greeting in many ways ("Rei
    Jarvis"), and the audio may start with words said before it, so everything up to the name
    goes. Without the name, the text is kept whole."""
    words = text.split()
    for index, word in enumerate(words):
        if _is_wake_name(word):
            return " ".join(words[index + 1 :]).lstrip(" ,.;:!?")
    return text
