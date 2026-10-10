"""Open favourite sites, or a domain said out loud ("g1 ponto com ponto br")."""

import re
import string
import webbrowser
from collections.abc import Callable, Mapping

from pydantic import BaseModel, Field

from jarvis.text import normalize
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

DOMAIN = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
SPOKEN_DOT = re.compile(r"\s*\b(?:ponto|dot)\b\s*")


def spoken_domain(text: str) -> str | None:
    """'youtube ponto com' / 'github dot com' / 'g1.com.br' -> the domain, else None."""
    candidate = SPOKEN_DOT.sub(".", normalize(text))
    return candidate if DOMAIN.fullmatch(candidate) else None


class OpenSiteParams(BaseModel):
    site: str = Field(
        min_length=1, description="A favourite site's name, a domain or a URL, e.g. 'youtube'"
    )


class OpenSiteTool(Tool[OpenSiteParams]):
    name = "open_site"
    description = "Open a website in the default browser: a configured favourite or a domain."
    params_model = OpenSiteParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:abre|abra|abrir|acessa|acesse|acessar|entra|entre|vai)"
                r"(?: (?:no|na|em|o|a|pro|pra|para o|para a))?(?: (?P<explicit>site|pagina))?"
                r"(?: (?:do|da|de))? (?P<site>.+)"
            ),
        ),
        en=(
            Intent(
                r"(?:open|go to|visit|browse to|navigate to)(?: (?:the|my))?"
                r"(?: (?P<explicit>site|website|page))?(?: (?:of|for))? (?P<site>.+)"
            ),
        ),
    )

    def __init__(
        self, favorites: Mapping[str, str], open_url: Callable[[str], object] = webbrowser.open
    ) -> None:
        self._favorites = {normalize(name): url for name, url in favorites.items()}
        self._open_url = open_url

    def accepts(self, args: Mapping[str, object]) -> bool:
        # "Abre o Spotify" also fits this pattern: leave it to open_app unless it is a site.
        return bool(args.get("explicit")) or self._resolve(str(args.get("site", ""))) is not None

    async def run(self, params: OpenSiteParams) -> ToolResult:
        resolved = self._resolve(params.site)
        if resolved is None:
            return ToolResult(Reply("sites.not_found", {"site": params.site}, cacheable=False))
        url, label = resolved
        self._open_url(url)
        return ToolResult(Reply("sites.opening", {"site": label}))

    def _resolve(self, site: str) -> tuple[str, str] | None:
        name = normalize(site)
        if name in self._favorites:
            return self._favorites[name], string.capwords(name)
        if site.startswith(("http://", "https://")):
            return site, site
        domain = spoken_domain(site)
        return (f"https://{domain}", domain) if domain else None
