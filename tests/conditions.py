"""Skip conditions shared by tests that need a real Windows desktop session."""

import os
import sys

import pytest

needs_desktop = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CI") == "true",
    reason="needs an interactive Windows desktop (hotkeys, windows, audio devices)",
)
