"""CPU, RAM and GPU load for the HUD gauges, sampled on the core loop (never on the Qt thread)."""

import asyncio

import psutil

from jarvis.core.events import EventSink, LoadSampled
from jarvis.windows.metrics import read_gpu


def sample_load() -> LoadSampled:
    """CPU use since the previous call (non-blocking), RAM, GPU load and VRAM; blocking for
    the few milliseconds NVML takes, so it runs on a worker thread."""
    memory = psutil.virtual_memory()
    gpu = read_gpu()
    return LoadSampled(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_percent=memory.percent,
        gpu_percent=gpu.load_percent if gpu else None,
        vram_percent=100 * gpu.vram_used_gb / gpu.vram_total_gb if gpu else None,
    )


async def watch_load(post: EventSink, every_s: float) -> None:
    psutil.cpu_percent(interval=None)  # the first reading only starts the measurement
    while True:
        await asyncio.sleep(every_s)
        post(await asyncio.to_thread(sample_load))
