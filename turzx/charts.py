"""Render actual telemetry history, preserving gaps instead of inventing samples."""

import math

from PIL import Image, ImageDraw

from .emojis import draw_caption
from .metrics import history_key, raw_value, reading, spec
from .render import font


def short_number(value, key):
    if key.startswith("network."):
        if value >= 2**20:
            return f"{value / 2**20:.1f}M"
        if value >= 1024:
            return f"{value / 1024:.0f}K"
    if value >= 10000:
        return f"{value / 1000:.0f}k"
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}"


def render_circle(item, metrics, gpu_id):
    image = Image.new("RGBA", (item.width, item.height))
    draw = ImageDraw.Draw(image)
    w, h = image.size
    intro = max(12, min(20, item.font_size + 3)) if item.show_label else 0
    if item.show_label:
        caption = font(intro - 3, False, item.font_family)
        label = item.label or spec(item.metric).label
        draw_caption(image, draw, (w / 2, 0), label, caption, w, item.label_color, item.emoji, "mt")

    diameter = min(w, h - intro) - 4
    x, y = (w - diameter) / 2, intro + (h - intro - diameter) / 2
    bounds = (x, y, x + diameter, y + diameter)
    thickness = item.chart_line_width + 2
    draw.ellipse(bounds, outline=(155, 180, 207, 70), width=thickness)

    current = reading(item.metric, metrics, gpu_id)
    value = raw_value(item.metric, metrics, gpu_id)
    maximum = item.chart_max
    if not maximum:
        samples = metrics.history.get(history_key(item.metric, metrics, gpu_id), ())
        maximum = 100 if spec(item.metric).unit == "%" else max(
            [1, value or 0] + [sample for _, sample in samples if sample is not None]
        )
    if value is not None and value > 0:
        draw.arc(bounds, -90, -90 + 360 * min(value / maximum, 1), fill=item.accent, width=thickness)

    size = min(item.font_size, diameter // 3)
    face = font(size, item.bold, item.font_family)
    inner_width = diameter - 2 * thickness - 4
    while size > 8 and draw.textlength(current.text, font=face) > inner_width:
        size -= 1
        face = font(size, item.bold, item.font_family)
    text = current.text
    if draw.textlength(text, font=face) > inner_width and value is not None:
        text = short_number(value, item.metric)
    draw.text((w / 2, y + diameter / 2), text, font=face, fill=item.color, anchor="mm")
    return image


def render_chart(item, metrics, gpu_id):
    if item.style == "chart_circle":
        return render_circle(item, metrics, gpu_id)
    image = Image.new("RGBA", (item.width, item.height))
    draw = ImageDraw.Draw(image)
    w, h = image.size
    current = reading(item.metric, metrics, gpu_id)
    caption_size = max(8, min(item.font_size, h // 4, 24))
    small = font(caption_size, False, item.font_family)
    label = item.label or spec(item.metric).label
    if item.show_label:
        draw_caption(image, draw, (0, 0), label, small, w * .54, item.label_color, item.emoji)
    value = current.text
    while value and draw.textlength(value, font=small) > (w * .45 if item.show_label else w):
        value = value[:-1]
    draw.text((w - 1, 0), value, font=small, fill=item.color, anchor="rt")
    samples = metrics.history.get(history_key(item.metric, metrics, gpu_id), ())
    now = metrics.sampled_at or (samples[-1][0] if samples else 0)
    start = now - item.chart_window
    samples = [(t, v) for t, v in samples if start <= t <= now]
    values = [v for _, v in samples if v is not None and math.isfinite(v)]
    maximum = item.chart_max or (100 if spec(item.metric).unit == "%" else max(1, max(values or [0]) * 1.1))
    left, right, top, bottom = 31, w - 3, caption_size + 6, h - 14
    if item.chart_grid:
        for fraction in (0, .5, 1):
            y = round(bottom - fraction * (bottom - top))
            draw.line((left, y, right, y), fill=(155, 180, 207, 65))
        for fraction in (0, .25, .5, .75, 1):
            x = round(left + fraction * (right - left))
            draw.line((x, top, x, bottom), fill=(155, 180, 207, 40))
    draw.text((left - 3, top), short_number(maximum, item.metric), font=font(8), fill=item.label_color, anchor="rt")
    draw.text((left - 3, bottom), "0", font=font(8), fill=item.label_color, anchor="rb")
    draw.text((left, h - 1), f"−{item.chart_window}s", font=font(8), fill=item.label_color, anchor="lb")
    draw.text((right, h - 1), "agora", font=font(8), fill=item.label_color, anchor="rb")
    segments, segment = [], []
    for timestamp, value in samples:
        if value is None or not math.isfinite(value):
            if segment:
                segments.append(segment)
                segment = []
            continue
        x = left + (timestamp - start) / item.chart_window * (right - left)
        y = bottom - min(1, max(0, value / maximum)) * (bottom - top)
        segment.append((x, y))
    if segment:
        segments.append(segment)
    overlay = Image.new("RGBA", image.size)
    plot = ImageDraw.Draw(overlay)
    rgb = tuple(int(item.accent[i:i + 2], 16) for i in (1, 3, 5))
    for points in segments:
        if item.style == "chart_area" and len(points) > 1:
            plot.polygon([(points[0][0], bottom), *points, (points[-1][0], bottom)], fill=rgb + (90,))
        if item.style == "chart_bars":
            bar_width = min(8, max(1, (right - left) / max(1, len(samples)) * .65))
            for x, y in points:
                plot.rectangle((max(left, x - bar_width / 2), y, min(right, x + bar_width / 2), bottom), fill=item.accent)
        else:
            if len(points) > 1:
                plot.line(points, fill=item.accent, width=item.chart_line_width, joint="curve")
            for x, y in points[-1:]:
                plot.ellipse((x - 1, y - 1, x + 1, y + 1), fill=item.accent)
    image.alpha_composite(overlay)
    if not values:
        message = "Coletando…" if current.available else "Sem leituras"
        ImageDraw.Draw(image).text(((left + right) / 2, (top + bottom) / 2), message,
                                  font=font(8), fill=item.label_color, anchor="mm")
    return image
