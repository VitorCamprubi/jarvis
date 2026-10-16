"""Starting JARVIS with Windows (ADR-044): a value in the user's Run registry key.

It starts the virtual environment's ``pythonw``, so no console window opens; Task Manager
lists it under start-up apps, where it can also be disabled.
"""

import sys
import winreg
from pathlib import Path
from typing import Any

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"


def launch_command(executable: str = sys.executable) -> str:
    return f'"{Path(executable).with_name("pythonw.exe")}" -m jarvis'


def enable(command: str | None = None, registry: Any = winreg) -> str:
    command = command or launch_command()
    with registry.CreateKeyEx(
        registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE
    ) as key:
        registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, command)
    return command


def disable(registry: Any = winreg) -> bool:
    """False when it was not enabled."""
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE
        ) as key:
            registry.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def current(registry: Any = winreg) -> str | None:
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = registry.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    return str(value)
