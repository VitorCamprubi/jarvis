"""The JARVIS process on Windows: a single instance, and errors shown without a console."""

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10
INSTANCE_MUTEX = "Local\\JARVIS-voice-assistant"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_held: dict[str, int] = {}  # mutex handles kept until the process ends


def claim_single_instance(name: str = INSTANCE_MUTEX) -> bool:
    """False when another JARVIS process already runs in this session (it holds the
    hotkey). Claiming again from the same process succeeds."""
    if name in _held:
        return True
    handle = _kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    if handle:
        _held[name] = handle
    return True


_windowless = False


def mark_windowless() -> None:
    """Called at start-up when there is no console at all: started by pythonw (ADR-044)."""
    global _windowless
    _windowless = True


def is_windowless() -> bool:
    return _windowless


def show_error(text: str) -> None:
    """A Windows message box: without a console, the only way to say why JARVIS stopped."""
    ctypes.windll.user32.MessageBoxW(None, text, "J.A.R.V.I.S.", MB_ICONERROR)
