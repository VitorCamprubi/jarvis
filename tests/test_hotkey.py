import threading

import pytest
from conditions import needs_desktop

from jarvis.activation import HotkeyError, HotkeyListener, parse_hotkey


def test_parse_letter_with_modifiers() -> None:
    hotkey = parse_hotkey("ctrl+alt+j")

    assert hotkey.modifiers == 0x0002 | 0x0001
    assert hotkey.virtual_key == ord("J")


def test_parse_is_case_and_space_insensitive() -> None:
    hotkey = parse_hotkey(" Ctrl + Shift + 5 ")

    assert (hotkey.modifiers, hotkey.virtual_key) == (0x0002 | 0x0004, ord("5"))


@pytest.mark.parametrize(
    ("text", "virtual_key"),
    [("win+f1", 0x70), ("ctrl+f24", 0x87), ("alt+space", 0x20), ("pause", 0x13)],
)
def test_parse_function_and_named_keys(text: str, virtual_key: int) -> None:
    assert parse_hotkey(text).virtual_key == virtual_key


@pytest.mark.parametrize(
    "text", ["", "ctrl+", "hyper+j", "ctrl+ctrl+j", "ctrl+alt+jj", "ctrl+f25", "ctrl+ç"]
)
def test_invalid_hotkeys_are_rejected(text: str) -> None:
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


@needs_desktop
def test_registered_hotkey_receives_a_real_key_press() -> None:
    import ctypes

    pressed = threading.Event()
    listener = HotkeyListener(parse_hotkey("ctrl+alt+shift+f24"), pressed.set)
    listener.start()
    try:
        user32 = ctypes.WinDLL("user32")
        keys = [0x11, 0x12, 0x10, 0x87]  # ctrl, alt, shift, F24: a combination nobody uses
        for key in keys:
            user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys):
            user32.keybd_event(key, 0, 2, 0)  # KEYEVENTF_KEYUP
        assert pressed.wait(2)
    finally:
        listener.stop()


@needs_desktop
def test_a_hotkey_already_in_use_is_reported() -> None:
    first = HotkeyListener(parse_hotkey("ctrl+alt+shift+f23"), lambda: None)
    first.start()
    try:
        with pytest.raises(HotkeyError, match="another program"):
            HotkeyListener(parse_hotkey("ctrl+alt+shift+f23"), lambda: None).start()
    finally:
        first.stop()
