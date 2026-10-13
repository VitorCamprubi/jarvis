"""Shared test set-up."""

import os

# Qt widgets are tested without a screen, here and in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
