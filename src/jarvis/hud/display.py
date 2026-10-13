"""The HUD as a whole: Qt application, window, tray icon, and the bridge from the core thread.

Qt owns the main thread (ADR-004). The core publishes events on its own thread; ``post``
emits them through a Qt signal, and Qt delivers each one on the main thread, where the
widgets live. Nothing here ever blocks: the window only draws what it is told.
"""

import logging
import signal
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication

from jarvis.config import HudConfig
from jarvis.core.events import Event, JarvisSpoke, UserSpoke
from jarvis.hud.links import open_link
from jarvis.hud.tray import Tray
from jarvis.hud.window import HudWindow
from jarvis.i18n import Language, Translator
from jarvis.tools.base import Link

log = logging.getLogger(__name__)

WATCH_MS = 250  # how often the Qt loop lets Python see Ctrl+C and checks start-up


class Bridge(QObject):
    """Created on the main thread; ``post`` may be called from any thread."""

    received = Signal(object)

    def post(self, event: Event) -> None:
        self.received.emit(event)  # queued to the main thread when posted from another one


class Hud:
    def __init__(
        self,
        config: HudConfig,
        translator: Translator,
        language: Language,
        stop_usd: float,
        settings_file: Path,
        opener: Callable[[Link], object] = open_link,
    ) -> None:
        existing = QApplication.instance()
        self._app = existing if isinstance(existing, QApplication) else QApplication([])
        self._app.setQuitOnLastWindowClosed(False)  # hiding the HUD must not quit JARVIS
        self.window = HudWindow(
            translator,
            language,
            QSettings(str(settings_file), QSettings.Format.IniFormat),
            opener,
            opacity=config.opacity,
            details_seconds=config.details_seconds,
            stop_usd=stop_usd,
        )
        self.tray = Tray(self.window, translator, language, self.quit)
        self._bridge = Bridge()
        self._bridge.received.connect(self._deliver)
        self.exit_code = 0

    def post(self, event: Event) -> None:
        """Thread-safe: the core thread calls this for every event."""
        self._bridge.post(event)

    def quit(self, code: int = 0) -> None:
        self.exit_code = code
        self._app.quit()

    def run(self, startup: Future[Any]) -> int:
        """Show the HUD and run Qt's event loop until the tray's Quit, Ctrl+C or a failed
        start-up. Returns the exit code."""
        self.window.place()
        self.window.show()
        self.tray.show()
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        # Python only handles Ctrl+C while Python code runs: tick regularly.
        watch = QTimer()
        watch.timeout.connect(lambda: self._check(startup))
        watch.start(WATCH_MS)
        self._app.exec()
        watch.stop()
        self.tray.hide()
        self.window.hide()
        return self.exit_code

    def _check(self, startup: Future[Any]) -> None:
        if startup.done() and startup.exception() is not None:
            log.error("Start-up failed: %s", startup.exception())
            self.quit(1)

    def _deliver(self, event: Event) -> None:
        self.window.handle(event)
        if isinstance(event, UserSpoke | JarvisSpoke):
            self.tray.retranslate(event.language)
