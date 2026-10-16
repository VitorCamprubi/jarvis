"""Render the README's demo GIF with the HUD's own code (ADR-047).

The real HUD window receives a scripted sequence of events, the same ones the core sends
while JARVIS works, and every frame is painted into an image. No window is shown and no
voice is involved, so the result is reproducible:

    uv run python scripts/render_hud_demo.py
"""

import random
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from jarvis import paths
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
from jarvis.hud.window import HudWindow
from jarvis.i18n import Language, Translator
from jarvis.tools.base import Link

OUTPUT = paths.PROJECT_ROOT / "docs" / "media" / "hud-demo.gif"
FPS = 10
MARGIN = 28
CANVAS_HEIGHT = 470
NEWS = (
    Link(
        "OpenAI aciona o FBI após achar escuta no escritório",
        "https://a",
        "web",
        "Tecnoblog · 18:42",
    ),
    Link(
        "Apple apresenta o HomeView, sua primeira tela inteligente",
        "https://b",
        "web",
        "The Verge · 17:05",
    ),
    Link("Gemini 4 Argon chega aos assinantes pagos", "https://c", "web", "Canaltech · 16:30"),
)
BULLETIN = (
    "Senhor, eis as principais notícias de tecnologia. A OpenAI acionou o FBI após encontrar "
    "uma escuta no escritório, e a Apple apresentou o HomeView, sua primeira tela inteligente."
)
# (second, event): what the core would send during two requests, one in each language.
SCRIPT: list[tuple[float, Event]] = [
    (0.0, StateChanged(State.IDLE)),
    (0.0, SpendingChanged(0.09)),
    (1.5, StateChanged(State.LISTENING)),
    (3.0, UserSpoke("Ei Jarvis, quais são as notícias de hoje?", Language.PT)),
    (3.0, StateChanged(State.THINKING)),
    (4.6, Shown(None, NEWS)),
    (4.6, StateChanged(State.SPEAKING)),
    (4.6, JarvisSpoke(BULLETIN, Language.PT)),
    (9.0, StateChanged(State.IDLE)),
    (10.0, StateChanged(State.LISTENING)),
    (11.2, UserSpoke("What's the weather like in London?", Language.EN)),
    (11.2, StateChanged(State.THINKING)),
    (12.4, StateChanged(State.SPEAKING)),
    (12.4, JarvisSpoke("It's 14 degrees in London right now, sir, and overcast.", Language.EN)),
    (15.0, StateChanged(State.IDLE)),
]
DURATION_S = 16.5


def desktop(width: int, height: int) -> QImage:
    """A dark desktop behind the translucent panel."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor(28, 36, 52))
    gradient.setColorAt(1, QColor(12, 16, 26))
    painter.fillRect(image.rect(), gradient)
    painter.end()
    return image


def frame(window: HudWindow, background: QImage) -> Image.Image:
    image = background.copy()
    window.render(image, QPoint(MARGIN, MARGIN), QRegion(), QWidget.RenderFlag.DrawChildren)
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    data = bytes(rgb.constBits())[: rgb.bytesPerLine() * rgb.height()]
    return Image.frombuffer(
        "RGB", (rgb.width(), rgb.height()), data, "raw", "RGB", rgb.bytesPerLine(), 1
    )


def load_wobble(seed: int) -> Callable[[float], LoadSampled]:
    rng = random.Random(seed)

    def sample(second: float) -> LoadSampled:
        busy = 1.0 if 3.0 <= second < 9.0 or 10.0 <= second < 15.0 else 0.0
        return LoadSampled(
            cpu_percent=8 + 14 * busy + rng.uniform(0, 6),
            ram_percent=61 + rng.uniform(0, 1.5),
            gpu_percent=4 + 38 * busy + rng.uniform(0, 8),
            vram_percent=52 + 3 * busy,
        )

    return sample


def main() -> None:
    QApplication([])
    settings = QSettings(str(OUTPUT.with_suffix(".ini")), QSettings.Format.IniFormat)
    window = HudWindow(
        Translator.load(),
        Language.PT,
        settings,
        lambda link: None,
        opacity=0.88,
        details_seconds=60,
        stop_usd=4.9,
    )
    background = desktop(window.width() + 2 * MARGIN, CANVAS_HEIGHT)
    load = load_wobble(seed=7)
    pending = sorted(SCRIPT, key=lambda item: item[0])
    frames: list[Image.Image] = []
    for index in range(int(DURATION_S * FPS)):
        second = index / FPS
        while pending and pending[0][0] <= second:
            window.handle(pending.pop(0)[1])
        if index % FPS == 0:
            window.handle(load(second))
        window.reactor.advance(1 / FPS)
        frames.append(frame(window, background))
    settings.clear()
    Path(settings.fileName()).unlink(missing_ok=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    palette = frames[len(frames) // 3].quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    frames[0].quantize(palette=palette).save(
        OUTPUT,
        save_all=True,
        append_images=[f.quantize(palette=palette) for f in frames[1:]],
        duration=1000 // FPS,
        loop=0,
        optimize=True,
    )
    print(f"{OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
