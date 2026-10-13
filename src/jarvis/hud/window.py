"""The HUD panel (ADR-039): reactor, state, language, load gauges and spending on top; what
was heard and the reply below; then lists and details, which fold away after a while.

The window floats above the others, lets clicks through to its links but never takes the
keyboard focus, and remembers where it was dragged to.
"""

from collections.abc import Callable, Sequence
from html import escape

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

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
from jarvis.hud.gauge import Gauge
from jarvis.hud.reactor import ReactorWidget, with_alpha
from jarvis.hud.theme import BACKGROUND, CYAN, MUTED, STATE_COLORS, TEXT, css, font
from jarvis.i18n import Language, Translator
from jarvis.tools.base import Link

WIDTH = 380
MARGIN = 24  # from the screen's edges, at the first start
PADDING = 14
CONTENT_WIDTH = WIDTH - 2 * PADDING
MAX_HEARD_CHARS = 160
MAX_REPLY_CHARS = 420
MAX_DETAILS_CHARS = 1500
MAX_LINKS = 10
POSITION_KEY = "hud/position"


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def links_html(links: Sequence[Link], more: str) -> str:
    """Titles come from web pages: always escaped, never trusted as markup."""
    rows = []
    for index, link in enumerate(links[:MAX_LINKS]):
        note = ""
        if link.note:
            note = f'<br><span style="color:{css(MUTED)}; font-size:8pt">{escape(link.note)}</span>'
        rows.append(
            f'<p style="margin:0 0 6px 0"><a href="link:{index}" '
            f'style="color:{css(CYAN)}; text-decoration:none">{escape(link.title)}</a>{note}</p>'
        )
    if len(links) > MAX_LINKS:
        rows.append(f'<p style="color:{css(MUTED)}">{escape(more)}</p>')
    return "".join(rows)


def details_html(details: str) -> str:
    text = escape(clip(details, MAX_DETAILS_CHARS)).replace("\n", "<br>")
    return f'<span style="color:{css(TEXT)}">{text}</span>'


def label(size: float, color: str, bold: bool = False, wrap: bool = False) -> QLabel:
    result = QLabel()
    result.setFont(font(size, bold))
    result.setStyleSheet(f"color: {color}; background: transparent;")
    if wrap:
        result.setWordWrap(True)
        result.setFixedWidth(CONTENT_WIDTH)
    return result


class HudWindow(QWidget):
    def __init__(
        self,
        translator: Translator,
        language: Language,
        settings: QSettings,
        open_link: Callable[[Link], object],
        *,
        opacity: float,
        details_seconds: float,
        stop_usd: float,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar button
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("J.A.R.V.I.S.")
        self.setFixedWidth(WIDTH)
        self._translator = translator
        self._language = language
        self._settings = settings
        self._open_link = open_link
        self._opacity = opacity
        self._stop_usd = stop_usd
        self._state = State.STARTING
        self._spent: float | None = None
        self._links: tuple[Link, ...] = ()
        self._drag_from: QPoint | None = None

        self.reactor = ReactorWidget(112)
        self.title = label(13, css(CYAN), bold=True)
        self.title.setText("J.A.R.V.I.S.")
        self.language_badge = label(8.5, css(MUTED))
        self.state_label = label(10, css(CYAN), bold=True)
        self.gauges = {name: Gauge(name) for name in ("CPU", "GPU", "VRAM", "RAM")}
        self.spending = label(8.5, css(MUTED))
        self.heard = label(9.5, css(MUTED), wrap=True)
        self.reply = label(10.5, css(TEXT), wrap=True)
        self.extra = label(9, css(TEXT), wrap=True)
        self.extra.setTextFormat(Qt.TextFormat.RichText)
        self.extra.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.extra.linkActivated.connect(self._clicked)
        self.extra.hide()
        self._fold_timer = QTimer(self)
        self._fold_timer.setSingleShot(True)
        self._fold_timer.setInterval(int(details_seconds * 1000))
        self._fold_timer.timeout.connect(self.fold)

        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.language_badge)
        status = QVBoxLayout()
        status.setSpacing(4)
        status.addLayout(header)
        status.addWidget(self.state_label)
        for gauge in self.gauges.values():
            status.addWidget(gauge)
        status.addWidget(self.spending)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.reactor, alignment=Qt.AlignmentFlag.AlignTop)
        top.addLayout(status)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        self._layout.setSpacing(8)
        self._layout.addLayout(top)
        self._layout.addWidget(self.heard)
        self._layout.addWidget(self.reply)
        self._layout.addWidget(self.extra)

        self._retranslate()
        self.heard.hide()
        self.reply.hide()
        self._fit()

    @property
    def language(self) -> Language:
        return self._language

    # Events from the core, delivered on the Qt thread by the bridge.

    def handle(self, event: Event) -> None:
        match event:
            case StateChanged(state=state):
                self._state = state
                self.reactor.set_state(state)
                self.state_label.setStyleSheet(f"color: {css(STATE_COLORS[state])};")
                self._retranslate()
            case UserSpoke(text=text, language=language):
                self._set_language(language)
                you = self._translator.text("hud.you", language)
                self.heard.setText(f"{you}: {clip(text, MAX_HEARD_CHARS)}")
                self.reply.clear()
                self.fold()
            case JarvisSpoke(text=text, language=language):
                self._set_language(language)
                self.reply.setText(clip(text, MAX_REPLY_CHARS))
            case Shown(details=details, links=links):
                self._show_extra(details, links)
            case SpendingChanged(spent_usd=spent):
                self._spent = spent
                self._retranslate()
            case LoadSampled() as load:
                self.gauges["CPU"].set_value(load.cpu_percent)
                self.gauges["RAM"].set_value(load.ram_percent)
                self.gauges["GPU"].set_value(load.gpu_percent)
                self.gauges["VRAM"].set_value(load.vram_percent)
        self.heard.setVisible(bool(self.heard.text()))
        self.reply.setVisible(bool(self.reply.text()))
        self._fit()

    def fold(self) -> None:
        """Put away the lists and details."""
        self._fold_timer.stop()
        self.extra.hide()
        self._links = ()
        self._fit()

    def place(self) -> None:
        """Where it was left, if that screen is still there; else the top right corner."""
        saved = self._settings.value(POSITION_KEY)
        if isinstance(saved, QPoint) and QGuiApplication.screenAt(saved + QPoint(20, 20)):
            self.move(saved)
            return
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(QPoint(screen.right() - WIDTH - MARGIN, screen.top() + MARGIN))

    # Qt overrides

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(with_alpha(BACKGROUND, self._opacity))
        painter.setPen(QPen(with_alpha(CYAN, 0.55), 1.2))
        painter.drawRoundedRect(area, 14, 14)
        painter.setPen(QPen(CYAN, 2.4))  # corner accents
        left, top, right, bottom = area.left(), area.top(), area.right(), area.bottom()
        painter.drawLine(int(left + 18), int(top), int(left + 70), int(top))
        painter.drawLine(int(right - 70), int(bottom), int(right - 18), int(bottom))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_from = None
            self._settings.setValue(POSITION_KEY, self.pos())

    # Internals

    def _show_extra(self, details: str | None, links: tuple[Link, ...]) -> None:
        self._links = links
        if links:
            more = self._translator.text("hud.more", self._language, count=len(links) - MAX_LINKS)
            self.extra.setText(links_html(links, more))
        elif details:
            self.extra.setText(details_html(details))
        else:
            return
        self.extra.show()
        self._fold_timer.start()

    def _clicked(self, href: str) -> None:
        prefix, _, number = href.partition(":")
        if prefix == "link" and number.isdigit() and int(number) < len(self._links):
            self._open_link(self._links[int(number)])

    def _set_language(self, language: Language) -> None:
        if language is not self._language:
            self._language = language
            self._retranslate()

    def _retranslate(self) -> None:
        self.language_badge.setText("PT-BR" if self._language is Language.PT else "EN")
        self.state_label.setText(self._translator.text(f"hud.state.{self._state}", self._language))
        if self._spent is not None:
            self.spending.setText(
                self._translator.text(
                    "hud.spending", self._language, spent=self._spent, stop=self._stop_usd
                )
            )

    def _fit(self) -> None:
        """Grow or shrink to the content; the width never changes."""
        self._layout.activate()
        height = self._layout.totalHeightForWidth(WIDTH)
        if height < 0:  # nothing wraps yet (no text): Qt has no height-for-width answer
            height = self._layout.totalSizeHint().height()
        self.setFixedHeight(height)
        self.resize(WIDTH, height)
