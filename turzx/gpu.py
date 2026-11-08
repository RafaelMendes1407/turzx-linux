"""Read-only GPU telemetry: Linux DRM/hwmon and optional nvidia-smi."""

import csv
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class GPU:
    id: str
    name: str
    vendor: str
    usage: float | None = None
    temperature: float | None = None
    memory_used: float | None = None  # GiB
    memory_total: float | None = None
    power: float | None = None       # W; APUs may report SoC power
    clock: float | None = None       # MHz
    fan_rpm: float | None = None
    fan_percent: float | None = None

    @property
    def memory_percent(self):
        if self.memory_total and self.memory_used is not None:
            return self.memory_used / self.memory_total * 100
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def read_text(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def read_number(path, divisor=1):
    value = number(read_text(path))
    return value / divisor if value is not None else None


@lru_cache(maxsize=16)
def pci_name(device, ids_path=Path("/usr/share/misc/pci.ids")):
    vendor = read_text(device / "vendor").removeprefix("0x")
    product = read_text(device / "device").removeprefix("0x")
    try:
        active = False
        for line in ids_path.read_text(errors="replace").splitlines():
            if line and not line.startswith(("\t", "#")):
                active = line.startswith(vendor + " ")
            elif active and line.startswith("\t" + product + " "):
                return line[5:].strip()
    except OSError:
        pass
    return ""


def drm_gpus(root=Path("/sys/class/drm")):
    result = []
    for card in sorted(root.glob("card*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        device = card / "device"
        vendor_id = read_text(device / "vendor")
        vendor = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}.get(vendor_id)
        if not vendor:
            continue
        bus = device.resolve().name
        name = read_text(device / "product_name") or pci_name(device) or f"{vendor} {read_text(device / 'device')}"
        hwmon = next(iter((device / "hwmon").glob("hwmon*")), device / "no-hwmon")
        power = read_number(hwmon / "power1_average", 1e6)
        if power is None:
            power = read_number(hwmon / "power1_input", 1e6)
        clock = read_number(hwmon / "freq1_input", 1e6)
        if clock is None:
            clock = read_number(card / "gt_cur_freq_mhz")  # older Intel i915
        result.append(GPU(
            id=f"pci:{bus}", name=f"{name} · {bus}", vendor=vendor,
            usage=read_number(device / "gpu_busy_percent"),
            temperature=read_number(hwmon / "temp1_input", 1000),
            memory_used=read_number(device / "mem_info_vram_used", 2**30),
            memory_total=read_number(device / "mem_info_vram_total", 2**30),
            power=power, clock=clock, fan_rpm=read_number(hwmon / "fan1_input")))
    return result


def parse_nvidia_csv(output):
    result = []
    for row in csv.reader(output.splitlines(), skipinitialspace=True):
        if len(row) != 11:
            continue
        uid, name, bus, *values = [v.strip() for v in row]
        if not uid.startswith("GPU-"):
            continue
        usage, temp, used, total, power, clock, fan, _ = [number(v) for v in values]
        result.append((bus.lower()[-12:], GPU(
            id=uid, name=name, vendor="NVIDIA", usage=usage, temperature=temp,
            memory_used=used / 1024 if used is not None else None,
            memory_total=total / 1024 if total is not None else None,
            power=power, clock=clock, fan_percent=fan)))
    return result


def sample_gpus():
    devices = drm_gpus()
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            query = "uuid,name,pci.bus_id,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,clocks.gr,fan.speed,index"
            response = subprocess.run([executable, "--query-gpu=" + query, "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=1.5, check=True)
            for bus, gpu in parse_nvidia_csv(response.stdout):
                devices = [d for d in devices if d.id != "pci:" + bus]
                devices.append(gpu)
        except (OSError, subprocess.SubprocessError):
            pass  # DRM identification remains; unsupported readings remain None.
    return sorted(devices, key=lambda d: d.id)
