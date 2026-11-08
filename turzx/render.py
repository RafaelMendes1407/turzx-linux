"""The same framebuffer is used by the preview and the physical panel."""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PALETTES = {
    "aurora": ("#0c1421", "#182435", "#65e6b6", "#e9f1f8", "#92a9bd"),
    "ocean": ("#081825", "#102d40", "#5fd6ff", "#edf8ff", "#8cb6cf"),
    "ember": ("#1c1513", "#302320", "#ffba70", "#fff4e8", "#c4a996"),
}


@lru_cache(maxsize=48)
def font(size, bold=False, family="sans"):
    base = {"sans": "DejaVuSans", "mono": "DejaVuSansMono", "serif": "DejaVuSerif"}.get(family, "DejaVuSans")
    name = base + ("-Bold.ttf" if bold else ".ttf")
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
    except OSError:
        return ImageFont.load_default()


def fit_text(draw, text, width, size, bold=False):
    while size > 9 and draw.textlength(text, font=font(size, bold)) > width:
        size -= 1
    return font(size, bold)


def rate(value):
    return f"{value / 2**20:.1f} MB/s" if value >= 2**20 else f"{value / 1024:.0f} KB/s"


@lru_cache(maxsize=8)
def cached_image(path, mtime, size):
    with Image.open(path) as source:
        return ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), size, Image.Resampling.LANCZOS)


def render(config, metrics):
    config.validate()
    w, h = config.size
    if config.mode == "custom":
        from .themes import load_theme, from_dict
        from .theme_render import render_theme
        theme = from_dict(config.custom_theme_data) if config.custom_theme_data is not None else load_theme(config.custom_theme)
        if theme.size != config.size:
            raise ValueError("A orientação da tela não corresponde ao tema. Ajuste no editor e aplique novamente.")
        return render_theme(theme, metrics)
    if config.mode == "image":
        if not config.image_path:
            raise ValueError("Escolha uma imagem antes de aplicar este modo.")
        path = Path(config.image_path)
        return cached_image(str(path), path.stat().st_mtime_ns, config.size).copy()
    bg, card, accent, white, muted = PALETTES[config.theme]
    image = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((18, 20, 24, 40), radius=3, fill=accent)
    d.text((34, 20), config.title or "MEU LINUX", font=fit_text(d, config.title, w - 140, 14, True), fill=white)
    d.text((w - 87, 22), "TURZX / 35", font=font(10), fill=muted)
    if config.mode == "clock":
        clock = metrics.now.strftime("%H:%M")
        face = font(82 if w == 480 else 70, True)
        d.text((w / 2, h / 2 - 36), clock, font=face, fill=white, anchor="mm")
        d.text((w / 2, h / 2 + 40), metrics.now.strftime("%d . %m . %Y"), font=font(20), fill=accent, anchor="mm")
        d.line((w * .25, h - 67, w * .75, h - 67), fill=card, width=2)
        d.text((w / 2, h - 45), "SEU TEMPO. SEU ESPAÇO.", font=font(11), fill=muted, anchor="mm")
        return image
    d.text((18, 45), metrics.now.strftime("%H:%M"), font=font(54, True), fill=white)
    d.text((w - 100, 68), metrics.now.strftime("%d / %m"), font=font(16), fill=accent)
    d.text((w - 100, 90), "SISTEMA ATIVO", font=font(9), fill=muted)

    def metric(x, y, cw, ch, label, value, detail, percent=None):
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=13, fill=card)
        d.text((x + 13, y + 10), label, font=font(10, True), fill=muted)
        d.text((x + 13, y + 28), value, font=fit_text(d, value, cw - 26, 30, True), fill=white)
        if percent is not None:
            yy = y + ch - 26
            d.rounded_rectangle((x + 13, yy, x + cw - 13, yy + 4), radius=2, fill=bg)
            length = (cw - 26) * min(100, max(0, percent)) / 100
            if length >= 2:
                d.rounded_rectangle((x + 13, yy, x + 13 + length, yy + 4), radius=2, fill=accent)
        d.text((x + 13, y + ch - 17), detail, font=fit_text(d, detail, cw - 26, 9), fill=muted)

    temp = "—" if metrics.temperature is None else f"{metrics.temperature:.0f}°C"
    temp_detail = "sensor indisponível" if metrics.temperature is None else "temperatura da CPU"
    if w == 480:
        metric(18, 119, 140, 103, "PROCESSADOR", f"{metrics.cpu:.0f}%", "uso da CPU", metrics.cpu)
        metric(170, 119, 140, 103, "MEMÓRIA", f"{metrics.memory:.0f}%",
               f"{metrics.memory_used:.1f} / {metrics.memory_total:.0f} GB", metrics.memory)
        metric(322, 119, 140, 103, "TEMPERATURA", temp, temp_detail)
        d.rounded_rectangle((18, 234, 462, 285), radius=12, fill=card)
        d.text((31, 244), "REDE", font=font(9, True), fill=muted)
        d.text((101, 251), f"↓ {rate(metrics.download)}", font=font(15, True), fill=accent, anchor="lm")
        d.text((286, 251), f"↑ {rate(metrics.upload)}", font=font(15), fill=white, anchor="lm")
    else:
        metric(18, 121, 136, 113, "PROCESSADOR", f"{metrics.cpu:.0f}%", "uso da CPU", metrics.cpu)
        metric(166, 121, 136, 113, "MEMÓRIA", f"{metrics.memory:.0f}%",
               f"{metrics.memory_used:.1f} / {metrics.memory_total:.0f} GB", metrics.memory)
        metric(18, 246, 136, 103, "TEMPERATURA", temp, temp_detail)
        metric(166, 246, 136, 103, "DISCO /", f"{metrics.disk:.0f}%", "espaço utilizado", metrics.disk)
        d.rounded_rectangle((18, 361, 302, 437), radius=12, fill=card)
        d.text((31, 372), "REDE", font=font(10, True), fill=muted)
        d.text((31, 393), f"↓ {rate(metrics.download)}", font=font(16, True), fill=accent)
        d.text((177, 393), f"↑ {rate(metrics.upload)}", font=font(13), fill=white)
    hours, minutes = divmod(metrics.uptime // 60, 60)
    d.text((18, h - 20), f"LIGADO HÁ {hours}H {minutes:02d}M", font=font(9), fill=muted)
    footer = f"DISCO /  {metrics.disk:.0f}%" if w == 480 else "LINUX • USB"
    d.text((w - 18, h - 20), footer, font=font(9), fill=muted, anchor="ra")
    return image


def test_pattern(size):
    image = Image.new("RGB", size)
    d = ImageDraw.Draw(image)
    w, h = size
    colors = ("#ffffff", "#ffff00", "#00ffff", "#00ff00", "#ff00ff", "#ff0000", "#0000ff")
    for i, color in enumerate(colors):
        d.rectangle((i * w // 7, 0, (i + 1) * w // 7, h), fill=color)
    d.rectangle((12, h // 2 - 42, w - 12, h // 2 + 42), fill="#0c1421")
    d.text((w // 2, h // 2 - 17), "TURZX • LINUX", font=font(26, True), fill="white", anchor="mm")
    d.text((w // 2, h // 2 + 20), f"{w} × {h}  /  TESTE DE CORES", font=font(13), fill="white", anchor="mm")
    return image
