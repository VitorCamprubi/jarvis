"""Locking, shutting down and restarting the PC."""

import ctypes
import subprocess
from collections.abc import Callable

Runner = Callable[..., subprocess.CompletedProcess[str]]


def lock_workstation() -> None:
    if not ctypes.WinDLL("user32").LockWorkStation():
        raise OSError("LockWorkStation failed")


def shut_down(restart: bool, delay_s: int, run: Runner = subprocess.run) -> None:
    """Schedule a shutdown or restart; `shutdown /a` still aborts it during the delay."""
    run(
        ["shutdown", "/r" if restart else "/s", "/t", str(delay_s)],
        capture_output=True,
        text=True,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
