"""Well-known filesystem locations.

JARVIS runs from a source checkout (uv installs the package in editable mode),
so the project root is derived from this file: src/jarvis/paths.py -> root.
"""

from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
CONFIG_DIR: Final = PROJECT_ROOT / "config"
ENV_FILE: Final = PROJECT_ROOT / ".env"
DATA_DIR: Final = PROJECT_ROOT / "data"
