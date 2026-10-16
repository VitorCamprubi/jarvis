import subprocess
import sys
import uuid

from jarvis.windows import autostart
from jarvis.windows.process import claim_single_instance


class FakeRegistry:
    """The few winreg calls autostart makes, on a dictionary."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    class _Key:
        def __enter__(self) -> FakeRegistry._Key:
            return self

        def __exit__(self, *exc_info: object) -> None:
            pass

    def CreateKeyEx(self, *args: object) -> FakeRegistry._Key:  # noqa: N802 (winreg's names)
        return self._Key()

    def OpenKey(self, *args: object) -> FakeRegistry._Key:  # noqa: N802
        return self._Key()

    def SetValueEx(self, key: object, name: str, reserved: int, kind: int, value: str) -> None:  # noqa: N802
        self.values[name] = value

    def QueryValueEx(self, key: object, name: str) -> tuple[str, int]:  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key: object, name: str) -> None:  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_autostart_runs_pythonw_without_a_console() -> None:
    command = autostart.launch_command(r"C:\Jarvis\.venv\Scripts\python.exe")

    assert command == r'"C:\Jarvis\.venv\Scripts\pythonw.exe" -m jarvis'


def test_autostart_can_be_switched_on_and_off() -> None:
    registry = FakeRegistry()

    assert autostart.current(registry) is None
    autostart.enable("pythonw -m jarvis", registry)
    assert autostart.current(registry) == "pythonw -m jarvis"
    assert autostart.disable(registry)
    assert autostart.current(registry) is None
    assert not autostart.disable(registry)  # already off


def test_only_one_jarvis_at_a_time() -> None:
    name = rf"Local\JARVIS-test-{uuid.uuid4()}"
    second_copy = [
        sys.executable,
        "-c",
        "import sys; from jarvis.windows.process import claim_single_instance as claim; "
        f"sys.exit(0 if claim({name!r}) else 3)",
    ]

    assert claim_single_instance(name)
    assert claim_single_instance(name)  # the same process again: still ours
    assert subprocess.run(second_copy, check=False).returncode == 3  # another process
