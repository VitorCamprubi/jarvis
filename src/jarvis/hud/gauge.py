"""A slim load gauge: label, bar and percentage."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from jarvis.hud.theme import AMBER, CYAN, MUTED, TEXT, font

LABEL_WIDTH = 38
VALUE_WIDTH = 40
HIGH_LOAD = 85.0  # the bar turns amber above this


class Gauge(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.value: float | None = None  # None: not available (no NVIDIA GPU)
        self.setFixedHeight(16)
        self.setMinimumWidth(150)

    def set_value(self, value: float | None) -> None:
        self.value = None if value is None else max(0.0, min(100.0, value))
        self.update()

    @property
    def text(self) -> str:
        return "—" if self.value is None else f"{self.value:.0f}%"

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt's name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        height = self.height()
        painter.setFont(font(8.5))
        painter.setPen(MUTED)
        painter.drawText(
            QRectF(0, 0, LABEL_WIDTH, height),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.label,
        )
        track = QRectF(LABEL_WIDTH, height / 2 - 3, self.width() - LABEL_WIDTH - VALUE_WIDTH, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        dim = CYAN.darker(300)
        painter.setBrush(dim)
        painter.drawRoundedRect(track, 3, 3)
        if self.value is not None:
            filled = QRectF(track)
            filled.setWidth(track.width() * self.value / 100)
            painter.setBrush(AMBER if self.value >= HIGH_LOAD else CYAN)
            painter.drawRoundedRect(filled, 3, 3)
        painter.setPen(TEXT)
        painter.drawText(
            QRectF(self.width() - VALUE_WIDTH, 0, VALUE_WIDTH, height),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            self.text,
        )
        painter.end()
