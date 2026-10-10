import string

import pytest

from jarvis.i18n import Language, Translator
from jarvis.i18n.translator import flatten


def placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


def test_both_locales_define_the_same_texts() -> None:
    translator = Translator.load()

    assert translator.keys(Language.PT) == translator.keys(Language.EN)


def test_every_variant_uses_the_same_placeholders_in_both_languages() -> None:
    translator = Translator.load()
    for key in translator.keys(Language.EN):
        variants = [v for language in Language for v in translator.variants(key, language)]
        expected = placeholders(variants[0])
        for variant in variants:
            assert placeholders(variant) == expected, f"{key}: {variant!r}"


def test_text_fills_placeholders_and_picks_a_variant() -> None:
    translator = Translator(
        {Language.EN: {"greet": ["Hello, {name}.", "Hi, {name}."]}, Language.PT: {}},
        choose=lambda variants: variants[-1],
    )

    assert translator.text("greet", Language.EN, name="sir") == "Hi, sir."


def test_missing_text_names_the_key_and_locale() -> None:
    translator = Translator({Language.EN: {}, Language.PT: {}})

    with pytest.raises(KeyError, match="pt-BR"):
        translator.text("nope", Language.PT)


def test_flatten_turns_tables_into_dotted_keys() -> None:
    assert flatten({"a": {"b": "x", "c": ["y", "z"]}}) == {"a.b": ["x"], "a.c": ["y", "z"]}


@pytest.mark.parametrize("bad", [42, [], ["ok", 3]])
def test_flatten_rejects_non_text_values(bad: object) -> None:
    with pytest.raises(ValueError, match="key"):
        flatten({"key": bad})


def test_language_locales() -> None:
    assert Language.PT.locale == "pt-BR"
    assert Language.EN.locale == "en"
