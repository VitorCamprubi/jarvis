"""Audio device lookup by (part of) name."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

import sounddevice as sd

Kind = Literal["input", "output"]
# MME resamples to any rate (16 kHz for Whisper); WASAPI and WDM-KS often refuse.
PREFERRED_HOST_API = "MME"


class DeviceNotFoundError(LookupError):
    """No audio device matches the configured name."""


def find_device(
    query: str,
    kind: Kind,
    devices: Sequence[Mapping[str, Any]] | None = None,
    host_apis: Sequence[Mapping[str, Any]] | None = None,
) -> int | None:
    """Index of the first device whose name contains ``query``; None means the Windows default."""
    if not query.strip():
        return None
    devices = list(sd.query_devices()) if devices is None else devices
    host_apis = list(sd.query_hostapis()) if host_apis is None else host_apis
    channels_key = f"max_{kind}_channels"
    matches = [
        index
        for index, device in enumerate(devices)
        if device[channels_key] > 0 and query.lower() in device["name"].lower()
    ]
    if not matches:
        names = sorted({device["name"] for device in devices if device[channels_key] > 0})
        raise DeviceNotFoundError(f"No {kind} device matches {query!r}. Available: {names}")
    preferred = [
        i for i in matches if host_apis[devices[i]["hostapi"]]["name"] == PREFERRED_HOST_API
    ]
    return (preferred or matches)[0]


def device_name(index: int | None, kind: Kind) -> str:
    """Human-readable name of a device index (None = the Windows default)."""
    info = sd.query_devices(index, kind=kind)
    return str(info["name"])


def list_devices(kind: Kind) -> list[str]:
    """Names of the devices of one kind, through the preferred host API."""
    host_apis = sd.query_hostapis()
    return [
        str(device["name"])
        for device in sd.query_devices()
        if device[f"max_{kind}_channels"] > 0
        and host_apis[device["hostapi"]]["name"] == PREFERRED_HOST_API
    ]
