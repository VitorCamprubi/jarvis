"""Windows integration: parsing is tested everywhere; real system calls are read-only."""

import asyncio
import json

from conditions import needs_desktop

from jarvis.windows.desktop import PROTECTED_PROCESSES, list_app_windows
from jarvis.windows.metrics import read_system_stats
from jarvis.windows.start_menu import StartApp, parse_start_apps
from jarvis.windows.volume import MasterVolume


def test_parse_start_apps_keeps_apps_only() -> None:
    raw = json.dumps(
        [
            {"Name": "Spotify", "AppID": r"C:\Users\Vitor\AppData\Roaming\Spotify\Spotify.exe"},
            {"Name": "Steam Support Center", "AppID": "http://support.steampowered.com/"},
            {"Name": "Uninstall Foo", "AppID": "Foo.Uninstall"},
            {"Name": "Desinstalar Bar", "AppID": "Bar.Uninstall"},
            {"Name": "", "AppID": "Nameless"},
            {"Name": "WhatsApp", "AppID": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
        ]
    )

    assert parse_start_apps(raw) == [
        StartApp("Spotify", r"C:\Users\Vitor\AppData\Roaming\Spotify\Spotify.exe"),
        StartApp("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"),
    ]


def test_parse_start_apps_accepts_a_single_object_and_nothing() -> None:
    assert parse_start_apps('{"Name": "Calculadora", "AppID": "Calc!App"}') == [
        StartApp("Calculadora", "Calc!App")
    ]
    assert parse_start_apps("") == []


def test_system_stats_are_plausible() -> None:
    stats = read_system_stats(cpu_sample_s=0.1)

    assert 0 <= stats.cpu_percent <= 100
    assert stats.ram_total_gb > 0
    assert stats.disks


@needs_desktop
def test_app_windows_exclude_the_shell() -> None:
    windows = list_app_windows()

    assert all(window.title for window in windows)
    assert not any(window.process.lower() in PROTECTED_PROCESSES for window in windows)


@needs_desktop
def test_master_volume_can_be_read() -> None:
    state = asyncio.run(MasterVolume().get())

    assert 0 <= state.level <= 100
