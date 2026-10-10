"""PC performance report: short when spoken, complete in the details (ADR-023)."""

import asyncio
from collections.abc import Callable

from pydantic import BaseModel

from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings
from jarvis.windows.metrics import SystemStats, read_system_stats


class SystemStatusParams(BaseModel):
    pass


class SystemStatusTool(Tool[SystemStatusParams]):
    name = "system_status"
    description = "Report the PC's performance: CPU, memory, disks and GPU load, temperature, VRAM."
    params_model = SystemStatusParams
    intents = phrasings(
        pt=(
            Intent(
                r"como (?:esta|ta|anda) o (?:pc|computador|sistema|desempenho)"
                r"(?: do (?:pc|computador))?"
            ),
            Intent(r"(?:status|desempenho|diagnostico|relatorio) do (?:pc|computador|sistema)"),
            Intent(r"(?:faz|faca|roda|rode) (?:um )?diagnostico(?: do (?:pc|computador|sistema))?"),
            Intent(r"(?:uso de|consumo de) (?:cpu|memoria|ram|gpu|recursos)"),
            Intent(r"como (?:estao|tao) os recursos(?: do (?:pc|computador))?"),
        ),
        en=(
            Intent(
                r"how(?:s| is) (?:the |my )?(?:pc|computer|system)"
                r"(?: doing| running| performing)?"
            ),
            Intent(r"(?:system|pc|computer) (?:status|performance|report)"),
            Intent(r"run (?:a )?(?:system )?diagnostics?"),
            Intent(r"(?:cpu|memory|ram|gpu) usage|status report"),
        ),
    )

    def __init__(self, read_stats: Callable[[], SystemStats] = read_system_stats) -> None:
        self._read_stats = read_stats

    async def run(self, params: SystemStatusParams) -> ToolResult:
        stats = await asyncio.to_thread(self._read_stats)
        figures: dict[str, object] = {
            "cpu": round(stats.cpu_percent),
            "ram": round(stats.ram_percent),
        }
        if stats.gpu is None:
            reply = Reply("system.summary_no_gpu", figures, cacheable=False)
        else:
            figures |= {"gpu": stats.gpu.load_percent, "gpu_temp": stats.gpu.temperature_c}
            reply = Reply("system.summary", figures, cacheable=False)
        return ToolResult(reply, details=describe(stats))


def describe(stats: SystemStats) -> str:
    lines = [
        f"CPU: {stats.cpu_percent:.0f}%",
        f"RAM: {stats.ram_percent:.0f}% ({stats.ram_used_gb:.1f} of {stats.ram_total_gb:.1f} GB)",
    ]
    lines += [
        f"Disk {disk.mount} {disk.used_percent:.0f}% used, {disk.free_gb:.0f} GB free"
        for disk in stats.disks
    ]
    if stats.gpu is not None:
        gpu = stats.gpu
        lines.append(
            f"GPU {gpu.name}: {gpu.load_percent}%, {gpu.temperature_c} °C, "
            f"VRAM {gpu.vram_used_gb:.1f} of {gpu.vram_total_gb:.1f} GB"
        )
    return "\n".join(lines)
