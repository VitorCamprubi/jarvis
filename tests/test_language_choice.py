import pytest

from jarvis.config import SttConfig
from jarvis.i18n import Language
from jarvis.stt.language import choose_language

CONFIG = SttConfig(
    model="large-v3-turbo",
    device="cuda",
    compute_type="float16",
    beam_size=5,
    short_audio_s=1.5,
    min_confidence=0.70,
    min_confidence_short=0.90,
)


def test_clear_portuguese() -> None:
    choice = choose_language([("pt", 0.95), ("en", 0.03)], 3.0, Language.EN, CONFIG)

    assert choice.language is Language.PT
    assert choice.detected


def test_other_languages_are_ignored() -> None:
    # Whisper's top guess is Spanish, but between pt and en Portuguese clearly wins.
    choice = choose_language([("es", 0.6), ("pt", 0.3), ("en", 0.05)], 3.0, Language.EN, CONFIG)

    assert choice.language is Language.PT
    assert choice.confidence == pytest.approx(0.3 / 0.35)


def test_uncertain_detection_keeps_the_previous_language() -> None:
    choice = choose_language([("pt", 0.5), ("en", 0.4)], 3.0, Language.EN, CONFIG)

    assert choice.language is Language.EN
    assert not choice.detected


def test_short_audio_needs_more_confidence() -> None:
    probabilities = [("en", 0.8), ("pt", 0.2)]

    assert choose_language(probabilities, 3.0, Language.PT, CONFIG).language is Language.EN
    assert choose_language(probabilities, 1.0, Language.PT, CONFIG).language is Language.PT


def test_no_pt_or_en_probability_keeps_the_previous_language() -> None:
    choice = choose_language([("fr", 0.9)], 3.0, Language.PT, CONFIG)

    assert choice.language is Language.PT
    assert not choice.detected
