import threading
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QImage, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from jarvis.config import HudConfig
from jarvis.core.events import (
    Event,
    JarvisSpoke,
    LoadSampled,
    Shown,
    SpendingChanged,
    StateChanged,
    UserSpoke,
)
from jarvis.core.state import State
from jarvis.hud import load
from jarvis.hud.display import Hud
from jarvis.hud.gauge import Gauge
from jarvis.hud.links import open_link
from jarvis.hud.reactor import ACTIVE_FRAME_MS, REST_FRAME_MS, ReactorWidget, reactor_icon
from jarvis.hud.window import MARGIN, POSITION_KEY, WIDTH, HudWindow
from jarvis.i18n import Language, Translator
from jarvis.tools.base import Link
from jarvis.windows.metrics import GpuStats

TRANSLATOR = Translator.load()
NEWS = Link("Apple lança novo iPhone", "https://tecnoblog.net/1", "web", "Tecnoblog · 14:05")


@pytest.fixture(scope="module", autouse=True)
def qt_app() -> Iterator[QApplication]:
    existing = QApplication.instance()
    yield existing if isinstance(existing, QApplication) else QApplication([])


class Opened:
    def __init__(self) -> None:
        self.links: list[Link] = []

    def __call__(self, link: Link) -> None:
        self.links.append(link)


def hud_window(tmp_path: Path, opener: Opened | None = None) -> HudWindow:
    settings = QSettings(str(tmp_path / "hud.ini"), QSettings.Format.IniFormat)
    return HudWindow(
        TRANSLATOR,
        Language.PT,
        settings,
        opener or Opened(),
        opacity=0.9,
        details_seconds=60,
        stop_usd=4.9,
    )


def feed(window: HudWindow, *events: Event) -> None:
    for event in events:
        window.handle(event)


def test_states_relabel_and_pace_the_reactor(tmp_path: Path) -> None:
    window = hud_window(tmp_path)

    feed(window, StateChanged(State.LISTENING))
    assert window.state_label.text() == "OUVINDO"
    assert window.reactor.frame_ms == ACTIVE_FRAME_MS

    feed(window, StateChanged(State.IDLE))
    assert window.state_label.text() == "EM ESPERA"
    assert window.reactor.frame_ms == REST_FRAME_MS


def test_what_was_heard_and_said(tmp_path: Path) -> None:
    window = hud_window(tmp_path)

    feed(window, UserSpoke("Abre o Spotify.", Language.PT))
    feed(window, JarvisSpoke("Abrindo Spotify, senhor.", Language.PT))
    assert window.heard.text() == "Você: Abre o Spotify."
    assert window.reply.text() == "Abrindo Spotify, senhor."

    feed(window, UserSpoke("Next song.", Language.EN))
    assert window.heard.text() == "You: Next song."
    assert window.reply.text() == ""  # the previous reply goes with the new question


def test_labels_follow_the_reply_language(tmp_path: Path) -> None:
    window = hud_window(tmp_path)

    feed(window, StateChanged(State.IDLE), UserSpoke("Status.", Language.EN))

    assert window.language_badge.text() == "EN"
    assert window.state_label.text() == "STANDING BY"


def test_links_are_listed_escaped_and_opened_on_click(tmp_path: Path) -> None:
    opened = Opened()
    window = hud_window(tmp_path, opened)
    sneaky = Link('<img src="x">Free <b>prize</b>', "https://example.com", "web")

    feed(window, Shown(None, (NEWS, sneaky)))

    assert not window.extra.isHidden()
    html = window.extra.text()
    assert "Apple lança novo iPhone" in html and "Tecnoblog · 14:05" in html
    assert "<img" not in html and "&lt;img" in html
    for href in ("link:1", "link:7", "javascript:alert(1)", "link:x"):
        window.extra.linkActivated.emit(href)
    assert opened.links == [sneaky]


def test_details_show_when_there_are_no_links(tmp_path: Path) -> None:
    window = hud_window(tmp_path)

    feed(window, Shown("CPU 12%\nRAM 48%", ()))

    assert "CPU 12%<br>RAM 48%" in window.extra.text()


def test_long_lists_are_cut_short(tmp_path: Path) -> None:
    window = hud_window(tmp_path)
    links = tuple(Link(f"Story {n}", f"https://x/{n}", "web") for n in range(12))

    feed(window, Shown(None, links))

    assert "Story 9" in window.extra.text() and "Story 10" not in window.extra.text()
    assert "e mais 2" in window.extra.text()


def test_the_panel_grows_with_content_and_folds_back(tmp_path: Path) -> None:
    window = hud_window(tmp_path)
    compact = window.height()

    feed(window, JarvisSpoke("Uma resposta bem longa, senhor. " * 8, Language.PT))
    feed(window, Shown(None, (NEWS,) * 3))
    expanded = window.height()
    window.fold()

    assert compact > 100  # already a full panel before anything was said
    assert expanded > compact
    assert window.extra.isHidden()
    assert window.height() < expanded
    assert window.width() == WIDTH


def test_spending_and_load_gauges(tmp_path: Path) -> None:
    window = hud_window(tmp_path)

    feed(window, SpendingChanged(0.0785), LoadSampled(12.4, 48.0, None, None))

    assert window.spending.text() == "Gasto da API: US$ 0.08 de 4.90"
    assert window.gauges["CPU"].text == "12%"
    assert window.gauges["GPU"].text == "—"  # no NVIDIA GPU


def test_the_window_floats_without_taking_the_focus(tmp_path: Path) -> None:
    window = hud_window(tmp_path)
    flags = window.windowFlags()

    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool  # no taskbar button
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_position_is_remembered_or_top_right(tmp_path: Path) -> None:
    window = hud_window(tmp_path)
    window.place()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    assert window.pos() == QPoint(screen.right() - WIDTH - MARGIN, screen.top() + MARGIN)

    settings = QSettings(str(tmp_path / "hud.ini"), QSettings.Format.IniFormat)
    settings.setValue(POSITION_KEY, QPoint(100, 120))
    settings.sync()
    moved = hud_window(tmp_path)
    moved.place()
    assert moved.pos() == QPoint(100, 120)


@pytest.mark.parametrize("state", list(State))
def test_the_reactor_draws_every_state(state: State) -> None:
    reactor = ReactorWidget(96)
    reactor.set_state(state)
    reactor.advance(0.5)
    image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    reactor.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)

    assert image.pixelColor(48, 48).lightness() > 200  # the white-hot core
    assert image.pixelColor(1, 1).alpha() < 30  # transparent outside the halo


def test_the_tray_icon_is_drawn() -> None:
    assert not reactor_icon(32).isNull()


def test_gauges_clamp_their_values() -> None:
    gauge = Gauge("CPU")

    gauge.set_value(140)

    assert gauge.text == "100%"


def test_events_from_another_thread_reach_the_qt_thread(tmp_path: Path) -> None:
    hud = Hud(
        HudConfig(enabled=True, opacity=0.9, details_seconds=60, load_seconds=2),
        TRANSLATOR,
        Language.PT,
        4.9,
        tmp_path / "hud.ini",
    )
    threads: list[str] = []
    handle = hud.window.handle

    def recording(event: Event) -> None:
        threads.append(threading.current_thread().name)
        handle(event)

    hud.window.handle = recording  # type: ignore[method-assign]
    core = threading.Thread(
        target=lambda: hud.post(UserSpoke("Oi.", Language.PT)), name="jarvis-core"
    )
    core.start()
    core.join()
    QCoreApplication.processEvents()

    assert threads == [threading.main_thread().name]
    assert hud.window.heard.text() == "Você: Oi."


def test_a_failed_start_up_ends_the_qt_loop(tmp_path: Path) -> None:
    hud = Hud(
        HudConfig(enabled=True, opacity=0.9, details_seconds=60, load_seconds=2),
        TRANSLATOR,
        Language.PT,
        4.9,
        tmp_path / "hud.ini",
    )
    startup: Future[None] = Future()
    startup.set_exception(RuntimeError("no microphone"))

    assert hud.run(startup) == 1


def test_the_tray_menu_follows_the_window(tmp_path: Path) -> None:
    hud = Hud(
        HudConfig(enabled=True, opacity=0.9, details_seconds=60, load_seconds=2),
        TRANSLATOR,
        Language.PT,
        4.9,
        tmp_path / "hud.ini",
    )
    assert hud.tray.toggle_action.text() == "Mostrar HUD"

    hud.tray.toggle_action.trigger()

    assert hud.window.isVisible()
    assert hud.tray.toggle_action.text() == "Esconder HUD"
    hud.tray.retranslate(Language.EN)
    assert hud.tray.quit_action.text() == "Quit JARVIS"
    hud.window.hide()


def test_only_web_pages_and_found_files_are_opened() -> None:
    browsed: list[str] = []
    files: list[Path] = []

    def opener(link: Link) -> bool:
        return open_link(link, browser=browsed.append, files=files.append)

    assert opener(NEWS)
    assert not opener(Link("x", "javascript:alert(1)", "web"))
    assert not opener(Link("x", "file:///C:/Windows/System32/cmd.exe", "web"))
    assert opener(Link("report.pdf", "C:/Docs/report.pdf", "file"))
    assert browsed == [NEWS.target]
    assert files == [Path("C:/Docs/report.pdf")]


def test_load_is_sampled_with_and_without_a_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(load, "read_gpu", lambda: GpuStats("RTX", 37, 55, 2.0, 8.0))
    sampled = load.sample_load()
    assert (sampled.gpu_percent, sampled.vram_percent) == (37, 25.0)
    assert 0 <= sampled.cpu_percent <= 100 and 0 < sampled.ram_percent <= 100

    monkeypatch.setattr(load, "read_gpu", lambda: None)
    assert load.sample_load().gpu_percent is None
