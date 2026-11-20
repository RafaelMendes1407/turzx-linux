"""Real Linux readings. Unavailable temperatures are displayed as unavailable."""

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading

import psutil

from .gpu import GPU, sample_gpus
from .history import History


@dataclass(frozen=True)
class Disk:
    usage: float
    used: float
    free: float
    total: float


def sample_disks():
    mounts = {"/"}
    mounts.update(partition.mountpoint for partition in psutil.disk_partitions())
    disks = {}
    for mount in sorted(mounts):
        try:
            usage = psutil.disk_usage(mount)
        except (OSError, psutil.Error):
            continue
        disks[mount] = Disk(usage.percent, usage.used / 2**30, usage.free / 2**30, usage.total / 2**30)
    return disks


def sample_disk_devices():
    devices = {}
    for path in sorted(Path("/sys/block").glob("*")):
        try:
            if "/devices/virtual/" in str(path.resolve()):
                continue
            sectors = int((path / "size").read_text())
        except (OSError, ValueError):
            continue
        devices[f"/dev/{path.name}"] = sectors * 512 / 2**30
    return devices


def disk_metadata():
    """Map mount paths to physical devices and filesystem labels."""
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--tree", "--output", "KNAME,LABEL,MODEL,MOUNTPOINTS"],
            capture_output=True, text=True, check=True, timeout=1,
        )
        devices = json.loads(result.stdout)["blockdevices"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return {}, {}
    models, volumes = {}, {}

    def visit(node, device):
        name = node.get("label") or node["kname"]
        for mount in node.get("mountpoints") or ():
            if mount and mount.startswith("/"):
                volumes[mount] = (device, name)
        for child in node.get("children", ()):
            visit(child, device)

    for node in devices:
        device = "/dev/" + node["kname"]
        models[device] = (node.get("label") or node.get("model") or "").strip()
        visit(node, device)
    return models, volumes


@dataclass
class Metrics:
    cpu: float
    memory: float
    memory_used: float
    memory_total: float
    disk: float | None
    temperature: float | None
    download: float
    upload: float
    uptime: int
    now: datetime
    cpu_name: str = "CPU"
    cores: int | None = None
    threads: int | None = None
    frequency: float | None = None
    per_core: list[float] = field(default_factory=list)
    gpus: list[GPU] = field(default_factory=list)
    sampled_at: float = 0
    history: dict = field(default_factory=dict)
    disks: dict[str, Disk] = field(default_factory=dict)
    disk_devices: dict[str, float] = field(default_factory=dict)
    disk_models: dict[str, str] = field(default_factory=dict)
    disk_volumes: dict[str, tuple[str, str]] = field(default_factory=dict)


class Sampler:
    def __init__(self):
        psutil.cpu_percent()
        psutil.cpu_percent(percpu=True)
        self.last_net = psutil.net_io_counters()
        self.last_time = time.monotonic()
        self.last_gpu_time = -10.0
        self.gpus = []
        self.disk_models, self.disk_volumes = {}, {}
        self.history = History()
        self.cpu_name = "CPU"
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    self.cpu_name = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        self.cores = psutil.cpu_count(logical=False)
        self.threads = psutil.cpu_count(logical=True)

    def sample(self):
        now = time.monotonic()
        elapsed = max(now - self.last_time, .001)
        net = psutil.net_io_counters()
        download = max(0, net.bytes_recv - self.last_net.bytes_recv) / elapsed
        upload = max(0, net.bytes_sent - self.last_net.bytes_sent) / elapsed
        self.last_net, self.last_time = net, now
        memory = psutil.virtual_memory()
        temperature = None
        try:
            sensors = psutil.sensors_temperatures()
            for name in ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz"):
                values = sensors.get(name, [])
                if values:
                    preferred = next((v for v in values if v.label in ("Tctl", "Package id 0")), values[0])
                    temperature = preferred.current
                    break
        except (OSError, AttributeError):
            pass
        frequency = None
        try:
            freq = psutil.cpu_freq()
            frequency = freq.current if freq else None
        except (OSError, NotImplementedError):
            pass
        if now - self.last_gpu_time >= 2:
            self.gpus = sample_gpus()
            self.disk_models, self.disk_volumes = disk_metadata()
            self.last_gpu_time = now
        disks = sample_disks()
        root = disks.get("/")
        metrics = Metrics(psutil.cpu_percent(), memory.percent, memory.used / 2**30,
                       memory.total / 2**30, root.usage if root else None, temperature,
                       download, upload, int(time.time() - psutil.boot_time()), datetime.now(),
                       self.cpu_name, self.cores, self.threads, frequency,
                       psutil.cpu_percent(percpu=True), self.gpus, sampled_at=now, disks=disks,
                       disk_devices=sample_disk_devices(), disk_models=self.disk_models,
                       disk_volumes=self.disk_volumes)
        metrics.history = self.history.record(metrics, now)
        return metrics


class LiveSampler:
    """Keep hardware reads and bounded GPU subprocesses off the GTK main thread."""

    def __init__(self):
        self.latest = None
        self.error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="turzx-sensors")
        self._thread.start()

    def _run(self):
        sampler = None
        while not self._stop.is_set():
            try:
                if sampler is None:
                    sampler = Sampler()
                self.latest = sampler.sample()
                self.error = ""
            except (OSError, RuntimeError, psutil.Error) as exc:
                self.error = str(exc)
            self._stop.wait(1)

    def close(self):
        self._stop.set()
