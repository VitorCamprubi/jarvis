"""Choose between Portuguese and English from Whisper's language probabilities (ADR-016)."""

from collections.abc import Iterable
from dataclasses import dataclass

from jarvis.config import SttConfig
from jarvis.i18n import Language


@dataclass(frozen=True)
class LanguageChoice:
    language: Language
    confidence: float  # share of the winner in P(pt) + P(en)
    detected: bool  # False when the previous language was kept for lack of confidence


def choose_language(
    probabilities: Iterable[tuple[str, float]],
    duration_s: float,
    previous: Language,
    config: SttConfig,
) -> LanguageChoice:
    """Restrict detection to pt/en; keep ``previous`` unless the winner is clear enough.

    Whisper may rank a third language first (Spanish for a short Portuguese command);
    only the pt and en probabilities count. Short audio needs more confidence, because
    that is where detection fails most.
    """
    scores = dict(probabilities)
    pt, en = scores.get(Language.PT.value, 0.0), scores.get(Language.EN.value, 0.0)
    if pt + en <= 0:
        return LanguageChoice(previous, 0.0, detected=False)
    winner = Language.PT if pt >= en else Language.EN
    confidence = max(pt, en) / (pt + en)
    required = (
        config.min_confidence_short if duration_s < config.short_audio_s else config.min_confidence
    )
    if confidence >= required:
        return LanguageChoice(winner, confidence, detected=True)
    return LanguageChoice(previous, confidence, detected=False)
