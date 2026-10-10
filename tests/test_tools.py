import asyncio
from collections.abc import Awaitable, Iterable

import pytest
from fakes import FakeVolume
from pydantic import ValidationError

from jarvis.tools.apps import AppIndex, OpenAppParams, OpenAppTool, spoken_name
from jarvis.tools.base import ToolResult
from jarvis.tools.close import CloseAppParams, CloseAppTool, find_app_windows
from jarvis.tools.lock import LockParams, LockTool
from jarvis.tools.media import MediaParams, MediaTool
from jarvis.tools.power import PowerParams, PowerTool
from jarvis.tools.sites import OpenSiteParams, OpenSiteTool, spoken_domain
from jarvis.tools.system import SystemStatusParams, SystemStatusTool
from jarvis.tools.volume import VolumeParams, VolumeTool
from jarvis.windows.desktop import AppWindow
from jarvis.windows.keys import VK_MEDIA_NEXT_TRACK
from jarvis.windows.metrics import DiskStats, GpuStats, SystemStats
from jarvis.windows.start_menu import StartApp

APPS = [
    StartApp("Spotify", r"C:\Users\Vitor\AppData\Roaming\Spotify\Spotify.exe"),
    StartApp("Visual Studio Code", "Microsoft.VisualStudioCode"),
    StartApp("IntelliJ IDEA 2026.2.3", r"{6D809377}\JetBrains\idea64.exe"),
    StartApp("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"),
]


def run(awaitable: Awaitable[ToolResult]) -> ToolResult:
    async def wait() -> ToolResult:
        return await awaitable

    return asyncio.run(wait())


# --- open_app --------------------------------------------------------------------------


class AppHarness:
    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self.started: list[StartApp] = []
        self.urls: list[str] = []
        self.loads = 0
        self.index = AppIndex(85, 1800, loader=self._load)
        self.tool = OpenAppTool(self.index, aliases or {}, self.started.append, self.urls.append)

    def _load(self) -> list[StartApp]:
        self.loads += 1
        return APPS


@pytest.mark.parametrize(
    ("spoken", "app"),
    [
        ("spotfy", "Spotify"),
        ("code", "Visual Studio Code"),
        ("intelij", "IntelliJ IDEA 2026.2.3"),
    ],
)
def test_open_app_finds_approximate_names(spoken: str, app: str) -> None:
    harness = AppHarness()

    result = run(harness.tool.run(OpenAppParams(name=spoken)))

    assert [started.name for started in harness.started] == [app]
    assert result.reply.key == "apps.opening"


def test_open_app_says_the_name_without_version() -> None:
    harness = AppHarness()

    result = run(harness.tool.run(OpenAppParams(name="intellij")))

    assert result.reply.params == {"app": "IntelliJ IDEA"}
    assert spoken_name("Visual Studio Code") == "Visual Studio Code"


def test_alias_can_open_a_url_in_the_default_browser() -> None:
    harness = AppHarness({"navegador": "https://www.google.com"})

    run(harness.tool.run(OpenAppParams(name="Navegador")))

    assert harness.urls == ["https://www.google.com"]
    assert harness.started == []


def test_alias_can_name_a_start_menu_app() -> None:
    harness = AppHarness({"editor": "Visual Studio Code"})

    run(harness.tool.run(OpenAppParams(name="editor")))

    assert [app.name for app in harness.started] == ["Visual Studio Code"]


def test_unknown_app_is_reported_and_not_cached() -> None:
    harness = AppHarness()

    result = run(harness.tool.run(OpenAppParams(name="photoshop")))

    assert harness.started == []
    assert result.reply.key == "apps.not_found"
    assert not result.reply.cacheable


def test_app_index_reloads_only_when_stale() -> None:
    now = [0.0]
    loads: list[int] = []

    def loader() -> list[StartApp]:
        loads.append(1)
        return APPS

    index = AppIndex(85, 60, loader=loader, clock=lambda: now[0])

    async def scenario() -> None:
        await index.find("spotify")
        now[0] = 30
        await index.find("whatsapp")
        now[0] = 100
        await index.find("spotify")

    asyncio.run(scenario())
    assert len(loads) == 2


# --- open_site -------------------------------------------------------------------------

FAVORITES = {"youtube": "https://www.youtube.com"}


@pytest.mark.parametrize(
    ("spoken", "domain"),
    [
        ("g1 ponto com ponto br", "g1.com.br"),
        ("github dot com", "github.com"),
        ("youtube.com", "youtube.com"),
        ("spotify", None),
        ("abre o", None),
    ],
)
def test_spoken_domain(spoken: str, domain: str | None) -> None:
    assert spoken_domain(spoken) == domain


def test_open_site_favourite_and_domain() -> None:
    opened: list[str] = []
    tool = OpenSiteTool(FAVORITES, opened.append)

    run(tool.run(OpenSiteParams(site="YouTube")))
    run(tool.run(OpenSiteParams(site="g1 ponto com ponto br")))

    assert opened == ["https://www.youtube.com", "https://g1.com.br"]


def test_open_site_leaves_app_names_to_open_app() -> None:
    tool = OpenSiteTool(FAVORITES, print)

    assert not tool.accepts({"site": "spotify"})
    assert tool.accepts({"site": "spotify", "explicit": "site"})


def test_unknown_site_is_reported() -> None:
    opened: list[str] = []

    result = run(OpenSiteTool(FAVORITES, opened.append).run(OpenSiteParams(site="amazon")))

    assert opened == []
    assert result.reply.key == "sites.not_found"


# --- system_status ---------------------------------------------------------------------


def stats(gpu: GpuStats | None) -> SystemStats:
    return SystemStats(12.4, 74.6, 11.9, 16.0, (DiskStats("C:\\", 69.6, 290.0),), gpu)


def test_system_status_summary_and_details() -> None:
    gpu = GpuStats("NVIDIA GeForce RTX 4060 Ti", 3, 44, 1.6, 8.0)

    result = run(SystemStatusTool(lambda: stats(gpu)).run(SystemStatusParams()))

    assert result.reply.key == "system.summary"
    assert result.reply.params == {"cpu": 12, "ram": 75, "gpu": 3, "gpu_temp": 44}
    assert not result.reply.cacheable
    assert result.details is not None
    assert "Disk C:\\ 70% used, 290 GB free" in result.details
    assert "VRAM 1.6 of 8.0 GB" in result.details


def test_system_status_without_gpu() -> None:
    result = run(SystemStatusTool(lambda: stats(None)).run(SystemStatusParams()))

    assert result.reply.key == "system.summary_no_gpu"


# --- media, lock -----------------------------------------------------------------------


def test_media_presses_the_matching_key() -> None:
    pressed: list[int] = []

    result = run(MediaTool(pressed.append).run(MediaParams(action="next")))

    assert pressed == [VK_MEDIA_NEXT_TRACK]
    assert result.reply.key == "media.next"


def test_lock_locks() -> None:
    locked: list[bool] = []

    run(LockTool(lambda: locked.append(True)).run(LockParams()))

    assert locked == [True]


# --- volume ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "params", "level"),
    [
        (50, VolumeParams(action="set", level=30), 30),
        (50, VolumeParams(action="up"), 60),
        (95, VolumeParams(action="up"), 100),
        (50, VolumeParams(action="down", step=20), 30),
        (5, VolumeParams(action="down"), 0),
    ],
)
def test_volume_levels(start: int, params: VolumeParams, level: int) -> None:
    volume = FakeVolume(start)

    result = run(VolumeTool(volume, 10).run(params))

    assert volume.state.level == level
    assert result.reply.params == {"level": level}


def test_setting_a_level_unmutes() -> None:
    volume = FakeVolume(40, muted=True)

    run(VolumeTool(volume, 10).run(VolumeParams(action="set", level=60)))

    assert not volume.state.muted


def test_mute_unmute_and_report() -> None:
    volume = FakeVolume(40)
    tool = VolumeTool(volume, 10)

    assert run(tool.run(VolumeParams(action="mute"))).reply.key == "volume.muted"
    assert volume.state.muted
    assert run(tool.run(VolumeParams(action="get"))).reply.key == "volume.current_muted"
    run(tool.run(VolumeParams(action="unmute")))
    assert run(tool.run(VolumeParams(action="get"))).reply.params == {"level": 40}


def test_volume_params_accept_spoken_numbers_and_need_a_level_to_set() -> None:
    assert VolumeParams.model_validate({"action": "set", "level": "trinta"}).level == 30
    with pytest.raises(ValidationError):
        VolumeParams(action="set")
    with pytest.raises(ValidationError):
        VolumeParams.model_validate({"action": "set", "level": "alto"})
    with pytest.raises(ValidationError):
        VolumeParams(action="set", level=150)


# --- power -----------------------------------------------------------------------------


def test_power_does_nothing_until_confirmed() -> None:
    calls: list[tuple[bool, int]] = []
    tool = PowerTool(lambda restart, delay: calls.append((restart, delay)))

    request = run(tool.run(PowerParams(action="restart")))

    assert request.reply.key == "power.confirm_restart"
    assert calls == []
    assert request.on_confirm is not None
    done = run(request.on_confirm())
    assert calls == [(True, 5)]
    assert done.reply.key == "power.restarting"


# --- close_app -------------------------------------------------------------------------

WINDOWS = [
    AppWindow(1, 100, "Spotify Premium", "Spotify"),
    AppWindow(2, 200, "main.py - Jarvis - Visual Studio Code", "Code"),
    AppWindow(3, 200, "README.md - Jarvis - Visual Studio Code", "Code"),
    AppWindow(4, 300, "WhatsApp", "ApplicationFrameHost"),
    AppWindow(5, 300, "Calculadora", "ApplicationFrameHost"),
]


def test_find_by_process_name_takes_all_its_windows() -> None:
    assert [w.handle for w in find_app_windows("spotify", WINDOWS, 85)] == [1]
    assert [w.handle for w in find_app_windows("visual studio code", WINDOWS, 85)] == [2, 3]


def test_store_apps_close_only_their_own_window() -> None:
    assert [w.handle for w in find_app_windows("whatsapp", WINDOWS, 85)] == [4]


def test_nothing_matches_an_app_that_is_not_open() -> None:
    assert find_app_windows("photoshop", WINDOWS, 85) == []


def test_close_asks_first_then_closes_the_matching_windows() -> None:
    closed: list[int] = []

    def close(windows: Iterable[AppWindow]) -> None:
        closed.extend(window.handle for window in windows)

    tool = CloseAppTool(85, list_windows=lambda: WINDOWS, close=close)
    request = run(tool.run(CloseAppParams(name="spotify")))

    assert request.reply.key == "close.confirm"
    assert request.reply.params == {"app": "Spotify"}
    assert closed == []
    assert request.on_confirm is not None
    run(request.on_confirm())
    assert closed == [1]


def test_close_reports_an_app_that_is_not_open() -> None:
    tool = CloseAppTool(85, list_windows=lambda: WINDOWS, close=print)

    result = run(tool.run(CloseAppParams(name="photoshop")))

    assert result.reply.key == "close.not_running"
    assert result.on_confirm is None


def test_close_refuses_the_computer_itself() -> None:
    assert not CloseAppTool(85, list, print).accepts({"name": "computador"})
