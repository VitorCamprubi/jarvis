"""Find files by name and open one of the results by voice (ADR-031).

The index holds file names under the configured folders, skipping build, dependency and
hidden folders, and is rebuilt in the background. Opening uses the file's default program,
except for executables and scripts, which are never run: their folder opens instead, with
the file selected.
"""

import asyncio
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from rapidfuzz import process

from jarvis.text import name_score, normalize, parse_number
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

log = logging.getLogger(__name__)

# Opening these would run code: show them in Explorer instead.
EXECUTABLE = {
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
    ".wsh", ".msi", ".msp", ".scr", ".pif", ".cpl", ".hta", ".jar", ".lnk", ".url", ".reg",
    ".py", ".pyw", ".sh",
}  # fmt: skip
ORDINALS = {
    "primeiro": 1, "primeira": 1, "first": 1,
    "segundo": 2, "segunda": 2, "second": 2,
    "terceiro": 3, "terceira": 3, "third": 3,
    "quarto": 4, "quarta": 4, "fourth": 4,
    "quinto": 5, "quinta": 5, "fifth": 5,
    "ultimo": -1, "ultima": -1, "last": -1,
}  # fmt: skip


def spoken_file_name(path: Path) -> str:
    """'Curriculo_Vitor-2026.pdf' -> 'Curriculo Vitor 2026', easier for the voice."""
    return " ".join(re.split(r"[_\-.]+", path.stem)).strip() or path.name


@dataclass(frozen=True)
class IndexedFile:
    path: Path
    name: str  # normalised stem, for matching


class FileIndex:
    def __init__(
        self,
        folders: Iterable[Path],
        skip_dirs: Iterable[str],
        max_age_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._folders = list(folders)
        self._skip = {name.lower() for name in skip_dirs}
        self._max_age_s = max_age_s
        self._clock = clock
        self._files: list[IndexedFile] = []
        self._loaded_at = float("-inf")
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        started = time.perf_counter()
        self._files = await asyncio.to_thread(self._scan)
        self._loaded_at = self._clock()
        log.info("File index: %d files in %.1f s", len(self._files), time.perf_counter() - started)

    async def search(self, query: str, limit: int, threshold: float) -> list[Path]:
        async with self._lock:
            if not self._files or self._clock() - self._loaded_at > self._max_age_s:
                await self.refresh()
        matches = process.extract(
            normalize(query),
            [indexed.name for indexed in self._files],
            scorer=name_score,
            score_cutoff=threshold,
            limit=limit,
        )
        return [self._files[index].path for _, _, index in matches]

    def _scan(self) -> list[IndexedFile]:
        files: list[IndexedFile] = []
        for folder in self._folders:
            for root, dirs, names in os.walk(folder):
                # Prune in place so os.walk never descends into skipped folders.
                dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in self._skip]
                files += [
                    IndexedFile(Path(root) / name, normalize(Path(name).stem))
                    for name in names
                    if not name.startswith(".")
                ]
        return files


class ResultList:
    """The last list of found files, so "abre o segundo" can pick from it."""

    def __init__(self) -> None:
        self.paths: list[Path] = []


class SearchFilesParams(BaseModel):
    query: str = Field(min_length=2, description="Part of the file's name, as the user said it")


class SearchFilesTool(Tool[SearchFilesParams]):
    name = "search_files"
    description = (
        "Search the user's Desktop, Documents and Downloads for files by name (approximate). "
        "Returns up to five matches; the user then says which one to open."
    )
    params_model = SearchFilesParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:procura|procure|procurar|encontra|encontre|encontrar|acha|ache|achar|busca"
                r"|busque|buscar|localiza|localize)(?: (?:o|a|os|as|meu|minha|meus|minhas))?"
                r"(?: (?:arquivo|arquivos|documento|documentos|planilha|pdf|foto|imagem))?"
                r"(?: (?:do|da|de|chamado|chamada|com o nome))? (?P<query>.+)"
            ),
            Intent(
                r"onde (?:esta|ta|fica)(?: (?:o|a|meu|minha))?(?: (?:arquivo|documento))? "
                r"(?P<query>.+)"
            ),
            Intent(r"(?:abre|abra|abrir) (?:o |a )?(?:arquivo|documento) (?P<query>.+)"),
        ),
        en=(
            Intent(
                r"(?:find|search for|look for|locate)(?: (?:the|my))?"
                r"(?: (?:file|files|document|documents))?(?: (?:called|named))? (?P<query>.+)"
            ),
            Intent(r"where is(?: (?:the|my))?(?: (?:file|document))? (?P<query>.+)"),
            Intent(r"open (?:the )?(?:file|document) (?P<query>.+)"),
        ),
    )

    def __init__(self, index: FileIndex, results: ResultList, limit: int, threshold: float) -> None:
        self._index = index
        self._results = results
        self._limit = limit
        self._threshold = threshold

    async def run(self, params: SearchFilesParams) -> ToolResult:
        paths = await self._index.search(params.query, self._limit, self._threshold)
        self._results.paths = paths
        if not paths:
            return ToolResult(
                Reply("files.none", {"query": params.query}, cacheable=False),
                model_data=f"No file matches {params.query!r}.",
            )
        listing = describe(paths)
        reply = Reply(
            "files.found_one" if len(paths) == 1 else "files.found",
            {"count": len(paths), "first": spoken_file_name(paths[0])},
            cacheable=False,
        )
        return ToolResult(reply, details=listing, model_data=listing)


def describe(paths: Sequence[Path]) -> str:
    lines = []
    for number, path in enumerate(paths, start=1):
        try:
            modified = f", modified {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d}"
        except OSError:
            modified = ""
        lines.append(f"{number}. {path.name} (in {path.parent}{modified})")
    return "\n".join(lines)


class OpenResultParams(BaseModel):
    position: int = Field(description="1 for the first result, 2 for the second... -1 for the last")

    @field_validator("position", mode="before")
    @classmethod
    def _spoken(cls, value: object) -> object:
        if isinstance(value, str):
            if value in ORDINALS:
                return ORDINALS[value]
            number = parse_number(value)
            if number is None:
                raise ValueError(f"not a position: {value!r}")
            return number
        return value


def open_path(path: Path) -> Literal["opened", "revealed"]:
    """Open with the default program; executables and scripts are only shown in Explorer."""
    if path.suffix.lower() in EXECUTABLE:
        subprocess.Popen(["explorer.exe", "/select,", str(path)])
        return "revealed"
    os.startfile(path)  # a document from the search results, never a program
    return "opened"


class OpenResultTool(Tool[OpenResultParams]):
    name = "open_search_result"
    description = "Open one of the files from the last search_files results, by position."
    params_model = OpenResultParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:abre|abra|abrir|mostra|mostre)(?: o| a)? (?P<position>primeir[oa]|segund[oa]"
                r"|terceir[oa]|quart[oa]|quint[oa]|ultim[oa])(?: (?:arquivo|resultado|item|opcao))?"
            ),
            Intent(r"(?:abre|abra) (?:o )?(?:numero|resultado|item) (?P<position>[a-z0-9]+)"),
        ),
        en=(
            Intent(
                r"open the (?P<position>first|second|third|fourth|fifth|last)"
                r"(?: (?:one|file|result))?"
            ),
            Intent(r"open (?:number|result) (?P<position>[a-z0-9]+)"),
        ),
    )

    def __init__(
        self,
        results: ResultList,
        opener: Callable[[Path], Literal["opened", "revealed"]] = open_path,
    ) -> None:
        self._results = results
        self._open = opener

    async def run(self, params: OpenResultParams) -> ToolResult:
        paths = self._results.paths
        if not paths:
            return ToolResult(Reply("files.no_results"))
        position = params.position
        if not (1 <= position <= len(paths) or position == -1):
            return ToolResult(Reply("files.no_such_result", {"position": position}))
        path = paths[position - 1] if position > 0 else paths[-1]
        outcome = self._open(path)
        key = "files.opening" if outcome == "opened" else "files.revealed"
        return ToolResult(Reply(key, {"name": spoken_file_name(path)}, cacheable=False))


def expand_folders(folders: Iterable[str]) -> list[Path]:
    """Configured folder strings ("~/Desktop") as paths."""
    return [Path(os.path.expandvars(folder)).expanduser() for folder in folders]
