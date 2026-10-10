"""PC performance: CPU, RAM and disks with psutil; GPU with NVIDIA's NVML (ADR-023)."""

from dataclasses import dataclass

import psutil

GIB = 1024**3


@dataclass(frozen=True)
class DiskStats:
    mount: str
    used_percent: float
    free_gb: float


@dataclass(frozen=True)
class GpuStats:
    name: str
    load_percent: int
    temperature_c: int
    vram_used_gb: float
    vram_total_gb: float


@dataclass(frozen=True)
class SystemStats:
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    disks: tuple[DiskStats, ...]
    gpu: GpuStats | None


def read_system_stats(cpu_sample_s: float = 0.3) -> SystemStats:
    """Blocking for ``cpu_sample_s``: CPU load is measured over that interval."""
    cpu = psutil.cpu_percent(interval=cpu_sample_s)
    memory = psutil.virtual_memory()
    disks = []
    for partition in psutil.disk_partitions():
        if "fixed" not in partition.opts:
            continue  # skip DVD drives, card readers and network shares
        usage = psutil.disk_usage(partition.mountpoint)
        disks.append(DiskStats(partition.mountpoint, usage.percent, usage.free / GIB))
    return SystemStats(
        cpu_percent=cpu,
        ram_percent=memory.percent,
        ram_used_gb=memory.used / GIB,
        ram_total_gb=memory.total / GIB,
        disks=tuple(disks),
        gpu=read_gpu(),
    )


def read_gpu() -> GpuStats | None:
    """The first NVIDIA GPU, or None when there is none (or no driver)."""
    import pynvml

    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError:
        return None
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return GpuStats(
            name=str(pynvml.nvmlDeviceGetName(handle)),
            load_percent=int(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu),
            temperature_c=int(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)),
            vram_used_gb=memory.used / GIB,
            vram_total_gb=memory.total / GIB,
        )
    except pynvml.NVMLError:
        return None
    finally:
        pynvml.nvmlShutdown()
