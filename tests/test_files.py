import asyncio
import os
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from typing import Literal

import pytest

from jarvis.tools import files
from jarvis.tools.base import ToolResult
from jarvis.tools.files import (
    FileIndex,
    OpenResultParams,
    OpenResultTool,
    ResultList,
    SearchFilesParams,
    SearchFilesTool,
    spoken_file_name,
)


def run(awaitable: Awaitable[ToolResult]) -> ToolResult:
    async def wait() -> ToolResult:
        return await awaitable

    return asyncio.run(wait())


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for relative in [
        "Documents/Curriculo_Vitor_2026.pdf",
        "Documents/Relatorio Mensal Outubro.docx",
        "Desktop/projeto/README.md",
        "Desktop/projeto/node_modules/curriculo/index.js",  # dependency folder: skipped
        "Desktop/projeto/.git/curriculo",  # hidden folder: skipped
        "Downloads/instalador_curriculo.exe",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return tmp_path


def index_of(tree: Path) -> FileIndex:
    return FileIndex(
        [tree / "Documents", tree / "Desktop", tree / "Downloads"], ["node_modules"], 600
    )


def test_index_skips_dependency_and_hidden_folders(tree: Path) -> None:
    found = asyncio.run(index_of(tree).search("curriculo", limit=5, threshold=75))

    assert {path.name for path in found} == {"Curriculo_Vitor_2026.pdf", "instalador_curriculo.exe"}


def test_search_tool_reports_and_remembers_the_results(tree: Path) -> None:
    results = ResultList()
    tool = SearchFilesTool(index_of(tree), results, limit=5, threshold=75)

    result = run(tool.run(SearchFilesParams(query="relatório mensal")))

    assert result.reply.key == "files.found_one"
    assert result.reply.params["first"] == "Relatorio Mensal Outubro"
    assert results.paths[0].name == "Relatorio Mensal Outubro.docx"
    assert result.model_data is not None and "Relatorio Mensal Outubro.docx" in result.model_data


def test_search_without_matches(tree: Path) -> None:
    result = run(
        SearchFilesTool(index_of(tree), ResultList(), 5, 75).run(
            SearchFilesParams(query="planilha")
        )
    )

    assert result.reply.key == "files.none"


def test_spoken_file_names_lose_separators() -> None:
    assert spoken_file_name(Path("Curriculo_Vitor-2026.final.pdf")) == "Curriculo Vitor 2026 final"


class Opener:
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def __call__(self, path: Path) -> Literal["opened", "revealed"]:
        self.opened.append(path)
        return "revealed" if path.suffix == ".exe" else "opened"


@pytest.mark.parametrize(("spoken", "index"), [("segundo", 1), ("last", -1), ("1", 0)])
def test_open_result_by_spoken_position(spoken: str, index: int) -> None:
    results = ResultList()
    results.paths = [Path("a.pdf"), Path("b.docx"), Path("c.txt")]
    opener = Opener()

    run(OpenResultTool(results, opener).run(OpenResultParams.model_validate({"position": spoken})))

    assert opener.opened == [results.paths[index]]


def test_open_result_without_a_search_or_out_of_range() -> None:
    results = ResultList()
    tool = OpenResultTool(results, Opener())

    assert run(tool.run(OpenResultParams(position=1))).reply.key == "files.no_results"
    results.paths = [Path("a.pdf")]
    assert run(tool.run(OpenResultParams(position=3))).reply.key == "files.no_such_result"


def test_programs_and_scripts_are_never_run(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[list[str]] = []
    started: list[Path] = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: launched.append(args))
    monkeypatch.setattr(os, "startfile", started.append, raising=False)

    assert files.open_path(Path("C:/Downloads/setup.EXE")) == "revealed"
    assert files.open_path(Path("C:/Docs/script.ps1")) == "revealed"
    assert files.open_path(Path("C:/Docs/report.pdf")) == "opened"

    assert [args[:2] for args in launched] == [["explorer.exe", "/select,"]] * 2
    assert started == [Path("C:/Docs/report.pdf")]
