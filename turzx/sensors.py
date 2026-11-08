"""Real Linux readings. Unavailable temperatures are displayed as unavailable."""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading

import psutil

from .gpu import GPU, sample_gpus
from .history import History


@dataclass
class Metrics:
    cpu: float
    memory: float
    memory_used: float
    memory_total: float
    disk: float
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


class Sampler:
    def __init__(self):
        psutil.cpu_percent()
        psutil.cpu_percent(percpu=True)
        self.last_net = psutil.net_io_counters()
        self.last_time = time.monotonic()
        self.last_gpu_time = -10.0
        self.gpus = []
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
            self.last_gpu_time = now
        metrics = Metrics(psutil.cpu_percent(), memory.percent, memory.used / 2**30,
                       memory.total / 2**30, psutil.disk_usage("/").percent, temperature,
                       download, upload, int(time.time() - psutil.boot_time()), datetime.now(),
                       self.cpu_name, self.cores, self.threads, frequency,
                       psutil.cpu_percent(percpu=True), self.gpus, sampled_at=now)
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
