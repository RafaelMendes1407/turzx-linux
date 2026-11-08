"""Bounded in-memory telemetry history. Never saved into a theme document."""

from collections import deque
import math

from .metrics import CATALOG, history_key, is_numeric, raw_value


class History:
    def __init__(self, seconds=300):
        self.seconds = seconds
        self.series = {}

    def record(self, metrics, timestamp):
        values = {}
        for key in list(CATALOG) + [f"cpu.core.{i}" for i in range(len(metrics.per_core))]:
            if not is_numeric(key):
                continue
            ids = [gpu.id for gpu in metrics.gpus] if key.startswith("gpu.") else ["auto"]
            for gpu_id in ids:
                values[history_key(key, metrics, gpu_id)] = raw_value(key, metrics, gpu_id)
        for key in self.series.keys() | values.keys():
            samples = self.series.setdefault(key, deque(maxlen=601))
            value = values.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                value = None
            samples.append((timestamp, value))
            while samples and samples[0][0] < timestamp - self.seconds:
                samples.popleft()
        for key in list(self.series):
            if key not in values and all(v is None for _, v in self.series[key]):
                del self.series[key]
        return {key: tuple(samples) for key, samples in self.series.items()}
