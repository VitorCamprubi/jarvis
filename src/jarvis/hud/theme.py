"""Colours and fonts of the HUD: cyan on deep blue, amber while thinking."""

from PySide6.QtGui import QColor, QFont

from jarvis.core.state import State

CYAN = QColor(64, 220, 255)
AMBER = QColor(255, 186, 74)
SLATE = QColor(110, 160, 180)
BACKGROUND = QColor(6, 18, 28)
TEXT = QColor(214, 242, 255)
MUTED = QColor(126, 176, 196)

STATE_COLORS = {
    State.STARTING: SLATE,
    State.IDLE: CYAN,
    State.LISTENING: CYAN,
    State.THINKING: AMBER,
    State.SPEAKING: CYAN,
}

FONT_FAMILY = "Bahnschrift"  # ships with Windows 10 and 11; Qt falls back elsewhere


def font(point_size: float, bold: bool = False) -> QFont:
    result = QFont(FONT_FAMILY)
    result.setPointSizeF(point_size)
    result.setBold(bold)
    return result


def css(color: QColor) -> str:
    return color.name()  # "#40dcff"
