"""The reactor: rotating rings around a pulsing core, coloured and paced by JARVIS's state.

Painted with QPainter (ADR-038): 30 frames per second while listening, thinking or speaking,
10 at rest, none while the HUD is hidden.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from jarvis.core.state import State
from jarvis.hud.theme import CYAN, STATE_COLORS

ACTIVE_FRAME_MS = 33
REST_FRAME_MS = 100
MAX_STEP_S = 0.2  # after a stall, jump instead of spinning wildly to catch up


@dataclass(frozen=True)
class Motion:
    spin: float  # degrees per second
    pulse_hz: float
    glow: float  # 0..1


MOTION = {
    State.STARTING: Motion(20, 0.3, 0.25),
    State.IDLE: Motion(12, 0.25, 0.35),
    State.LISTENING: Motion(90, 1.2, 0.9),
    State.THINKING: Motion(240, 2.0, 0.8),
    State.SPEAKING: Motion(60, 3.0, 1.0),
}
ACTIVE = {State.LISTENING, State.THINKING, State.SPEAKING}


def with_alpha(color: QColor, alpha: float) -> QColor:
    result = QColor(color)
    result.setAlphaF(max(0.0, min(1.0, alpha)))
    return result


def paint_reactor(
    painter: QPainter, area: QRectF, color: QColor, angle: float, pulse: float, glow: float
) -> None:
    """Draw the reactor inside ``area``; ``pulse`` goes from 0 to 1."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = area.center()
    radius = min(area.width(), area.height()) / 2

    halo = QRadialGradient(center, radius)
    halo.setColorAt(0.0, with_alpha(color, 0.45 * glow))
    halo.setColorAt(0.55, with_alpha(color, 0.15 * glow))
    halo.setColorAt(1.0, with_alpha(color, 0.0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(center, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def ring(fraction: float) -> QRectF:
        r = radius * fraction
        return QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)

    outer = QPen(color, radius * 0.07)
    outer.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(outer)
    for segment in range(12):  # Qt angles: 1/16 degree, counter-clockwise
        painter.drawArc(ring(0.80), int((angle + segment * 30) * 16), 18 * 16)

    inner = QPen(with_alpha(color, 0.7), radius * 0.03)
    painter.setPen(inner)
    for arc in range(3):
        painter.drawArc(ring(0.60), int((-1.5 * angle + arc * 120) * 16), 80 * 16)

    ticks = QPen(with_alpha(color, 0.55), radius * 0.02)
    painter.setPen(ticks)
    for tick in range(6):
        theta = math.radians(angle * 0.5 + tick * 60)
        start, end = radius * 0.42, radius * 0.50
        painter.drawLine(
            QPointF(center.x() + start * math.cos(theta), center.y() + start * math.sin(theta)),
            QPointF(center.x() + end * math.cos(theta), center.y() + end * math.sin(theta)),
        )

    core_radius = radius * (0.24 + 0.06 * pulse)
    core = QRadialGradient(center, core_radius)
    core.setColorAt(0.0, QColor(255, 255, 255, 235))
    core.setColorAt(0.45, with_alpha(color, 0.9))
    core.setColorAt(1.0, with_alpha(color, 0.0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(core)
    painter.drawEllipse(center, core_radius, core_radius)


def reactor_icon(size: int = 64) -> QPixmap:
    """A still reactor, for the tray icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_reactor(painter, QRectF(0, 0, size, size), CYAN, 15, 0.6, 0.9)
    painter.end()
    return pixmap


class ReactorWidget(QWidget):
    def __init__(self, size: int = 128, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = State.STARTING
        self._angle = 0.0
        self._time = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(REST_FRAME_MS)

    @property
    def state(self) -> State:
        return self._state

    @property
    def frame_ms(self) -> int:
        return self._timer.interval()

    def set_state(self, state: State) -> None:
        self._state = state
        self._timer.setInterval(ACTIVE_FRAME_MS if state in ACTIVE else REST_FRAME_MS)
        self.update()

    def advance(self, seconds: float) -> None:
        self._time += seconds
        self._angle = (self._angle + MOTION[self._state].spin * seconds) % 360

    def showEvent(self, event: object) -> None:  # noqa: N802 (Qt's name)
        self._clock.restart()
        self._timer.start()

    def hideEvent(self, event: object) -> None:  # noqa: N802
        self._timer.stop()  # nothing to animate while hidden

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        motion = MOTION[self._state]
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * motion.pulse_hz * self._time)
        painter = QPainter(self)
        paint_reactor(
            painter,
            QRectF(self.rect()),
            STATE_COLORS[self._state],
            self._angle,
            pulse,
            motion.glow,
        )
        painter.end()

    def _tick(self) -> None:
        self.advance(min(self._clock.restart() / 1000, MAX_STEP_S))
        self.update()
