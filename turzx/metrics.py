"""Selectable sources shared by the editor and the framebuffer renderer."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Metric:
    category: str
    label: str
    unit: str = ""


CATALOG = {
    "cpu.usage": Metric("cpu", "Uso da CPU", "%"),
    "cpu.temperature": Metric("cpu", "Temperatura", "°C"),
    "cpu.cores": Metric("cpu", "Núcleos físicos"),
    "cpu.threads": Metric("cpu", "Threads lógicas"),
    "cpu.frequency": Metric("cpu", "Frequência", "MHz"),
    "cpu.name": Metric("cpu", "Modelo da CPU"),
    "gpu.usage": Metric("gpu", "Uso da GPU", "%"),
    "gpu.temperature": Metric("gpu", "Temperatura", "°C"),
    "gpu.memory_percent": Metric("gpu", "Uso da VRAM", "%"),
    "gpu.memory_used": Metric("gpu", "VRAM utilizada", "GiB"),
    "gpu.memory_total": Metric("gpu", "VRAM total", "GiB"),
    "gpu.power": Metric("gpu", "Potência / SoC", "W"),
    "gpu.clock": Metric("gpu", "Frequência", "MHz"),
    "gpu.fan_rpm": Metric("gpu", "Ventoinha", "RPM"),
    "gpu.fan_percent": Metric("gpu", "Ventoinha", "%"),
    "gpu.name": Metric("gpu", "Modelo da GPU"),
    "memory.usage": Metric("memory", "Uso da RAM", "%"),
    "memory.used": Metric("memory", "RAM utilizada", "GiB"),
    "memory.total": Metric("memory", "RAM total", "GiB"),
    "disk.usage": Metric("system", "Uso do disco /", "%"),
    "network.download": Metric("network", "Download"),
    "network.upload": Metric("network", "Upload"),
    "system.uptime": Metric("system", "Tempo ligado"),
    "clock.time": Metric("system", "Hora"),
    "clock.date": Metric("system", "Data"),
    "text": Metric("system", "Texto livre"),
}
CATEGORIES = {"cpu": "CPU", "gpu": "GPU", "memory": "Memória", "network": "Rede", "system": "Sistema / texto"}


def spec(key):
    if isinstance(key, str) and re.fullmatch(r"cpu\.core\.\d{1,4}", key):
        return Metric("cpu", f"Thread {int(key.rsplit('.', 1)[1]) + 1}", "%")
    if not isinstance(key, str) or key not in CATALOG:
        raise ValueError("Métrica desconhecida.")
    return CATALOG[key]


def is_numeric(key):
    spec(key)
    return key not in ("text", "clock.time", "clock.date", "cpu.name", "gpu.name")


def selected_gpu(metrics, gpu_id="auto"):
    if gpu_id in ("auto", "inherit"):
        return metrics.gpus[0] if metrics.gpus else None
    return next((gpu for gpu in metrics.gpus if gpu.id == gpu_id), None)


def history_key(key, metrics, gpu_id="auto"):
    if key.startswith("gpu."):
        gpu = selected_gpu(metrics, gpu_id)
        return key + "@" + (gpu.id if gpu else gpu_id)
    return key


def raw_value(key, metrics, gpu_id="auto"):
    spec(key)
    if key.startswith("gpu."):
        gpu = selected_gpu(metrics, gpu_id)
        return getattr(gpu, key.split(".", 1)[1], None) if gpu else None
    if key.startswith("cpu.core."):
        index = int(key.rsplit(".", 1)[1])
        return metrics.per_core[index] if index < len(metrics.per_core) else None
    attrs = {"cpu.usage": "cpu", "cpu.temperature": "temperature", "cpu.cores": "cores",
             "cpu.threads": "threads", "cpu.frequency": "frequency", "cpu.name": "cpu_name",
             "memory.usage": "memory", "memory.used": "memory_used", "memory.total": "memory_total",
             "disk.usage": "disk", "network.download": "download", "network.upload": "upload",
             "system.uptime": "uptime"}
    return getattr(metrics, attrs[key]) if key in attrs else None


@dataclass(frozen=True)
class Reading:
    text: str
    percent: float | None = None
    available: bool = True


def reading(key, metrics, gpu_id="auto", text="Meu texto"):
    info = spec(key)
    if key == "text":
        return Reading(text)
    if key == "system.uptime":
        hours, minutes = divmod(metrics.uptime // 60, 60)
        return Reading(f"{hours}h {minutes:02d}m")
    if key.startswith("clock."):
        return Reading(metrics.now.strftime("%H:%M:%S" if key == "clock.time" else "%d/%m/%Y"))
    value = raw_value(key, metrics, gpu_id)
    if value is None:
        return Reading("N/D", available=False)
    if key.startswith("network."):
        return Reading(f"{value / 2**20:.1f} MiB/s" if value >= 2**20 else f"{value / 1024:.0f} KiB/s")
    if isinstance(value, str):
        return Reading(value)
    formatted = f"{value:.1f}" if info.unit == "GiB" else f"{value:.0f}"
    return Reading(formatted + (f" {info.unit}" if info.unit else ""),
                   min(100, max(0, value)) if info.unit == "%" else None)
