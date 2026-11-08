"""Render nested containers, using the exact geometry edited on the canvas."""

from PIL import Image, ImageChops, ImageDraw

from .metrics import reading, spec
from .render import font
from .themes import Item, decode_background
from .charts import render_chart


def ellipsis(draw, text, face, width):
    if draw.textlength(text, font=face) <= width:
        return text
    while text and draw.textlength(text + "…", font=face) > width:
        text = text[:-1]
    return text + "…" if text else ""


def render_item(item, metrics, gpu_id):
    gpu_id = gpu_id if item.gpu_id == "inherit" else item.gpu_id
    if item.style.startswith("chart_"):
        return render_chart(item, metrics, gpu_id)
    image = Image.new("RGBA", (item.width, item.height))
    d = ImageDraw.Draw(image)
    value = reading(item.metric, metrics, gpu_id, item.text)
    label = item.label or spec(item.metric).label
    label_font = font(max(8, min(12, item.font_size - 2)), False, item.font_family)
    value_font = font(item.font_size, item.bold, item.font_family)
    w, h = item.width, item.height
    if item.style == "line":
        value_width = min(w, max(w * .45, d.textlength(value.text, font=value_font)))
        if item.show_label and item.metric != "text":
            left = ellipsis(d, label, label_font, max(0, w - value_width - 6))
            d.text((0, h / 2), left, font=label_font, fill=item.label_color, anchor="lm")
        shown = ellipsis(d, value.text, value_font, value_width if item.show_label else w)
        anchor = "r" if item.show_label and item.metric != "text" else {"left": "l", "center": "m", "right": "r"}[item.align]
        d.text(({"l": 0, "m": w / 2, "r": w}[anchor], h / 2), shown, font=value_font, fill=item.color, anchor=anchor + "m")
    else:
        y = 0
        if item.show_label:
            d.text((0, 0), ellipsis(d, label, label_font, w), font=label_font, fill=item.label_color)
            y = 15
        face = value_font
        size = item.font_size
        reserved = 8 if item.style == "bar" else 0
        while size > 8 and (d.textlength(value.text, font=face) > w or size + y + reserved > h):
            size -= 1
            face = font(size, item.bold, item.font_family)
        anchor = {"left": "l", "center": "m", "right": "r"}[item.align]
        d.text(({"l": 0, "m": w / 2, "r": w}[anchor], y), ellipsis(d, value.text, face, w), font=face, fill=item.color, anchor=anchor + "t")
        if item.style == "bar" and h >= 24:
            d.rounded_rectangle((0, h - 5, w - 1, h - 1), radius=2, fill="#324156")
            if value.percent is not None and value.percent > 0:
                d.rounded_rectangle((0, h - 5, max(1, (w - 1) * value.percent / 100), h - 1), radius=2, fill=item.accent)
    return image


def render_theme(theme, metrics):
    theme.validate()
    if theme.background_image:
        image = decode_background(theme.background_image).resize(theme.size, Image.Resampling.LANCZOS).convert("RGBA")
    else:
        image = Image.new("RGBA", theme.size, theme.background)
    for c in theme.top_level():
        if isinstance(c, Item):
            image.alpha_composite(render_item(c, metrics, "auto"), (c.x, c.y))
            continue
        panel = Image.new("RGBA", (c.width, c.height))
        d = ImageDraw.Draw(panel)
        rgb = tuple(int(c.background[i:i + 2], 16) for i in (1, 3, 5))
        d.rounded_rectangle((0, 0, c.width - 1, c.height - 1), radius=c.radius,
                            fill=rgb + (c.opacity,), outline=c.border if c.border_width else None, width=c.border_width)
        if c.show_title:
            face = font(c.title_size, True)
            d.text((10, 9), ellipsis(d, c.title, face, c.width - 20), font=face, fill=c.foreground)
        for item in c.items:
            panel.alpha_composite(render_item(item, metrics, c.gpu_id), (item.x, item.y))
        mask = Image.new("L", panel.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, c.width - 1, c.height - 1), radius=c.radius, fill=255)
        panel.putalpha(ImageChops.multiply(panel.getchannel("A"), mask))
        image.alpha_composite(panel, (c.x, c.y))
    return image.convert("RGB")


def editor_preview(model, metrics, grid=True):
    image = render_theme(model.theme, metrics).convert("RGBA")
    overlay = Image.new("RGBA", image.size)
    d = ImageDraw.Draw(overlay)
    # Always visible; the editor checkbox controls snapping, not visibility.
    for x in range(0, image.width, 8):
        for y in range(0, image.height, 8):
            d.point((x + 1, y + 1), fill=(0, 0, 0, 135))
            d.point((x, y), fill=(220, 237, 255, 120))
    rectangles = [(i.x, i.y, i.width, i.height) for i in model.theme.items]
    for c in model.theme.containers:
        rectangles.append((c.x, c.y, c.width, c.height))
        rectangles.extend((c.x + i.x, c.y + i.y, i.width, i.height) for i in c.items)
        if not c.items:
            d.text((c.x + c.width / 2, c.y + c.height / 2 + 8), "Solte informações aqui", font=font(9),
                   anchor="mm", fill="#8da4bd")
    for x, y, w, h in rectangles:
        for px, py in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
            d.rectangle((px - 1, py - 1, px + 1, py + 1), fill="#c6dcee", outline="#112031")
    rect = model.bounds()
    if rect:
        x, y, w, h = rect
        d.rectangle((x, y, x + w - 1, y + h - 1), outline="#78e7bd", width=2)
        d.rectangle((x + w - 9, y + h - 9, x + w - 1, y + h - 1), fill="#78e7bd", outline="#11231f")
        d.line((x + w // 2, 0, x + w // 2, image.height), fill=(110, 231, 183, 80))
        d.line((0, y + h // 2, image.width, y + h // 2), fill=(110, 231, 183, 80))
    return Image.alpha_composite(image, overlay).convert("RGB")
