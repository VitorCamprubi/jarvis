"""Global push-to-talk hotkey through the Win32 RegisterHotKey API (ADR-011).

Windows notifies only the registered combination, so there is no keyboard hook and no
CPU use while idle. RegisterHotKey delivers WM_HOTKEY to the thread that registered it,
so the listener owns a thread running a Win32 message loop.
"""

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000  # holding the keys down fires once, not repeatedly
NAMED_KEYS = {
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "insert": 0x2D,
    "pause": 0x13,
}
VK_F1 = 0x70
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1
START_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    virtual_key: int
    text: str


class HotkeyError(RuntimeError):
    """The hotkey is invalid or could not be registered."""


def parse_hotkey(text: str) -> Hotkey:
    """Parse e.g. "ctrl+alt+j" into Win32 modifier flags and a virtual-key code."""
    parts = [part.strip().lower() for part in text.split("+")]
    if any(not part for part in parts):
        raise HotkeyError(f"Invalid hotkey {text!r}")
    *modifier_names, key = parts
    modifiers = 0
    for name in modifier_names:
        if name not in MODIFIERS:
            raise HotkeyError(f"Unknown modifier {name!r} in {text!r}; use {sorted(MODIFIERS)}")
        if modifiers & MODIFIERS[name]:
            raise HotkeyError(f"Repeated modifier {name!r} in {text!r}")
        modifiers |= MODIFIERS[name]
    return Hotkey(modifiers, _virtual_key(key, text), text)


def _virtual_key(key: str, text: str) -> int:
    if len(key) == 1 and (key.isascii() and key.isalnum()):
        return ord(key.upper())  # VK codes for A-Z and 0-9 equal their ASCII codes
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return VK_F1 + int(key[1:]) - 1
    if key in NAMED_KEYS:
        return NAMED_KEYS[key]
    raise HotkeyError(f"Unknown key {key!r} in {text!r}")


def _user32() -> Any:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    return user32


class HotkeyListener:
    def __init__(self, hotkey: Hotkey, on_press: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_press = on_press
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self) -> None:
        """Register the hotkey; raises HotkeyError if another program already uses it."""
        if sys.platform != "win32":
            raise HotkeyError("Global hotkeys are only supported on Windows")
        self._thread = threading.Thread(target=self._run, name="jarvis-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_S):
            raise HotkeyError("The hotkey thread did not start")
        if self._error is not None:
            raise HotkeyError(
                f"Cannot register {self._hotkey.text!r} (another program may be using it): "
                f"{self._error}"
            )

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            _user32().PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(START_TIMEOUT_S)

    def _run(self) -> None:
        user32 = _user32()
        self._thread_id = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        modifiers = self._hotkey.modifiers | MOD_NOREPEAT
        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers, self._hotkey.virtual_key):
            self._error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        try:
            # GetMessageW blocks until a message arrives; it returns 0 on WM_QUIT, -1 on error.
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    try:
                        self._on_press()
                    except Exception:
                        log.exception("Hotkey handler failed")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
