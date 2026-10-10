"""Open application windows, and closing them gracefully (ADR-024).

Closing posts WM_CLOSE, exactly what clicking the window's X does: the app may still ask to
save. Shell and system windows, and JARVIS's own console, are never listed.
"""

import ctypes
import os
from collections.abc import Iterable
from ctypes import wintypes
from dataclasses import dataclass

import psutil

# C signature of the callback EnumWindows calls once per window: BOOL f(HWND, LPARAM).
ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WM_CLOSE = 0x0010
GW_OWNER = 4
DWMWA_CLOAKED = 14  # hidden UWP windows still report themselves as visible
PROTECTED_PROCESSES = {
    "explorer",
    "dwm",
    "csrss",
    "winlogon",
    "lockapp",
    "searchhost",
    "searchapp",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "textinputhost",
}


@dataclass(frozen=True)
class AppWindow:
    handle: int
    pid: int
    title: str
    process: str  # executable name without ".exe", e.g. "Spotify"


def list_app_windows() -> list[AppWindow]:
    """Visible, top-level, titled windows of ordinary applications."""
    user32 = ctypes.WinDLL("user32")
    dwmapi = ctypes.WinDLL("dwmapi")
    own_console = ctypes.WinDLL("kernel32").GetConsoleWindow()
    windows: list[AppWindow] = []

    def visit(handle: int, _: int) -> bool:
        if not user32.IsWindowVisible(handle) or user32.GetWindow(handle, GW_OWNER):
            return True
        if handle == own_console or _is_cloaked(dwmapi, handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        process = _process_name(pid.value)
        if process and pid.value != os.getpid() and process.lower() not in PROTECTED_PROCESSES:
            windows.append(AppWindow(handle, pid.value, buffer.value, process))
        return True

    user32.EnumWindows(ENUM_WINDOWS_PROC(visit), 0)
    return windows


def close_windows(windows: Iterable[AppWindow]) -> None:
    user32 = ctypes.WinDLL("user32")
    for window in windows:
        user32.PostMessageW(window.handle, WM_CLOSE, 0, 0)


def _is_cloaked(dwmapi: ctypes.WinDLL, handle: int) -> bool:
    cloaked = ctypes.c_int(0)
    result = dwmapi.DwmGetWindowAttribute(
        handle, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and cloaked.value != 0


def _process_name(pid: int) -> str | None:
    try:
        name = psutil.Process(pid).name()
    except psutil.NoSuchProcess, psutil.AccessDenied:
        return None
    return name.removesuffix(".exe").removesuffix(".EXE")
