"""The tray icon: show or hide the HUD, and quit JARVIS."""

from collections.abc import Callable

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from jarvis.hud.reactor import reactor_icon
from jarvis.i18n import Language, Translator


class Tray:
    def __init__(
        self,
        window: QWidget,
        translator: Translator,
        language: Language,
        quit_app: Callable[[], object],
        on_toggle: Callable[[bool], object] = lambda visible: None,
    ) -> None:
        self._window = window
        self._on_toggle = on_toggle
        self._translator = translator
        self._icon = QSystemTrayIcon(QIcon(reactor_icon()))
        self._icon.setToolTip("J.A.R.V.I.S.")
        self._menu = QMenu()
        self.toggle_action = QAction(self._menu)
        self.toggle_action.triggered.connect(self._toggle)
        self.quit_action = QAction(self._menu)
        self.quit_action.triggered.connect(quit_app)
        self._menu.addAction(self.toggle_action)
        self._menu.addSeparator()
        self._menu.addAction(self.quit_action)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._activated)
        self._language = language
        self.retranslate(language)

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    def retranslate(self, language: Language) -> None:
        self._language = language
        key = "hud.hide" if self._window.isVisible() else "hud.show"
        self.toggle_action.setText(self._translator.text(key, language))
        self.quit_action.setText(self._translator.text("hud.quit", language))

    def refresh(self) -> None:
        """After the window was shown or hidden by someone else."""
        self.retranslate(self._language)

    def _toggle(self) -> None:
        self._window.setVisible(not self._window.isVisible())
        self.retranslate(self._language)
        self._on_toggle(self._window.isVisible())

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # a left click
            self._toggle()
