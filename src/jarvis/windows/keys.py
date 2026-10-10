"""Simulated media keys (ADR-022): they reach whichever player is active, Spotify included."""

import ctypes

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


def press_key(virtual_key: int) -> None:
    user32 = ctypes.WinDLL("user32")
    user32.keybd_event(virtual_key, 0, KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(virtual_key, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
