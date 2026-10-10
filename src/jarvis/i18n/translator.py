"""Looks up localised texts by key, e.g. ``translator.text("pipeline.heard", Language.EN)``.

Locale files are TOML; nested tables become dotted keys. A key holds one phrase or a
list of variants, from which one is picked at random so JARVIS does not sound canned.
"""

import random
import tomllib
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from typing import Any

from jarvis.i18n.language import Language

Catalog = Mapping[str, Sequence[str]]


class Translator:
    def __init__(
        self,
        catalogs: Mapping[Language, Catalog],
        choose: Callable[[Sequence[str]], str] = random.choice,
    ) -> None:
        self._catalogs = catalogs
        self._choose = choose

    @classmethod
    def load(cls) -> Translator:
        """Load the locale files shipped in jarvis/i18n/locales."""
        locales = files("jarvis.i18n").joinpath("locales")
        catalogs = {
            language: flatten(
                tomllib.loads(locales.joinpath(f"{language.locale}.toml").read_text("utf-8"))
            )
            for language in Language
        }
        return cls(catalogs)

    def text(self, key: str, language: Language, **params: object) -> str:
        return self._choose(self.variants(key, language)).format(**params)

    def variants(self, key: str, language: Language) -> Sequence[str]:
        try:
            return self._catalogs[language][key]
        except KeyError:
            raise KeyError(f"Missing text {key!r} for {language.locale}") from None

    def keys(self, language: Language) -> set[str]:
        return set(self._catalogs[language])


def flatten(table: Mapping[str, Any], prefix: str = "") -> dict[str, list[str]]:
    """{"a": {"b": "x"}} -> {"a.b": ["x"]}; single phrases become one-item lists."""
    flat: dict[str, list[str]] = {}
    for name, value in table.items():
        key = f"{prefix}{name}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, f"{key}."))
        elif isinstance(value, str):
            flat[key] = [value]
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            flat[key] = value
        else:
            raise ValueError(f"Text {key!r} must be a string or a non-empty list of strings")
    return flat
