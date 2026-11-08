#!/usr/bin/env python3
"""Reproducible documentation assets. All telemetry is synthetic, never sampled."""

from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from turzx.gpu import GPU
from turzx.history import History
from turzx.sensors import Metrics
from turzx.theme_render import editor_preview, render_theme
from turzx.themes import EditorModel, Item, Theme


def demo():
    theme = Theme(id="0" * 31 + "1", name="Livre · Telemetria", background="#0b1422")

    def item(metric, x, y, width, height, **props):
        value = Item(id=f"{len(theme.items) + 2:032x}", metric=metric, x=x, y=y,
                     width=width, height=height, z=len(theme.items), gpu_id="auto", **props)
        theme.items.append(value)
        return value

    item("text", 16, 16, 290, 24, text="TURZX  /  STUDIO", style="value",
         show_label=False, font_size=19, align="left", color="#eaf3ff")
    item("clock.time", 318, 19, 146, 24, style="value", show_label=False,
         font_size=17, color="#9cb3ce", font_family="mono")
    item("cpu.usage", 16, 54, 284, 51, style="value", label="PROCESSADOR",
         align="left", font_size=32, color="#70e7be")
    item("memory.usage", 318, 54, 146, 51, style="bar", label="MEMÓRIA",
         align="left", font_size=26, color="#9bbcff", accent="#9bbcff")
    graph = item("cpu.usage", 16, 124, 284, 124, style="chart_area", label="CPU · 60 segundos",
                 font_size=12, accent="#70e7be")
    item("network.download", 318, 124, 146, 124, style="chart_bars", label="REDE",
         font_size=10, accent="#9bbcff")
    item("cpu.temperature", 16, 268, 130, 25, label="CPU", font_size=18)
    item("gpu.usage", 168, 268, 132, 25, label="GPU", font_size=18)
    item("memory.used", 318, 268, 146, 25, label="RAM", font_size=18)
    theme.validate()

    history = History()
    for second in range(61):
        cpu = 42 + 17 * math.sin(second / 7) + 8 * math.sin(second / 2.5)
        metrics = Metrics(cpu, 48, 15.4, 32, 37, 56, (1.4 + .65 * math.sin(second / 5)) * 2**20,
                          240 * 1024, 7200 + second, datetime(2026, 1, 1, 14, 32),
                          cpu_name="CPU de demonstração", cores=8, threads=16, frequency=3800,
                          per_core=[cpu] * 16, gpus=[GPU("demo", "GPU de demonstração", "AMD", usage=64)],
                          sampled_at=second)
        metrics.history = history.record(metrics, second)
    model = EditorModel(theme)
    model.selection = (None, graph.id)
    return model, metrics


def main():
    model, metrics = demo()
    images = ROOT / "docs/images"
    examples = ROOT / "examples"
    images.mkdir(parents=True, exist_ok=True)
    examples.mkdir(exist_ok=True)
    render_theme(model.theme, metrics).save(images / "free-telemetry.png")
    editor_preview(model, metrics, False).save(images / "editor-guides.png")
    (examples / "free-telemetry.json").write_text(
        json.dumps(asdict(model.theme), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Exemplo e imagens gerados com dados fictícios fixos.")


if __name__ == "__main__":
    main()
