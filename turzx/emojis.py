"""Emoji palette and color glyphs for the USB framebuffer."""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont


EMOJIS = {
    "🌡️": "Termômetro", "🔥": "Fogo", "❄️": "Frio", "☀️": "Sol",
    "💻": "Computador", "⚙️": "Engrenagem", "🧠": "Memória", "💾": "Disco",
    "📶": "Sinal", "⬇️": "Download", "⬆️": "Upload", "⚡": "Energia",
    "🔋": "Bateria", "🕒": "Relógio", "📅": "Calendário", "📊": "Gráfico",
    "✅": "Normal", "⚠️": "Atenção", "🛑": "Crítico", "ℹ️": "Informação",
    "🟢": "Círculo verde", "🟡": "Círculo amarelo", "🔴": "Círculo vermelho",
}


@lru_cache(maxsize=1)
def emoji_font():
    for directory in ("truetype/noto", "noto", "noto-emoji"):
        try:
            return ImageFont.truetype(f"/usr/share/fonts/{directory}/NotoColorEmoji.ttf", 109)
        except OSError:
            continue
    return None


@lru_cache(maxsize=192)
def emoji_image(emoji, size):
    face = emoji_font()
    if face is None:
        return None
    x, y, right, bottom = face.getbbox(emoji)
    glyph = Image.new("RGBA", (right - x, bottom - y))
    ImageDraw.Draw(glyph).text((-x, -y), emoji, font=face, embedded_color=True)
    bounds = glyph.getbbox()
    if not bounds:
        return None
    glyph = glyph.crop(bounds)
    glyph.thumbnail((size, size), Image.Resampling.LANCZOS)
    return glyph


def draw_caption(image, draw, xy, text, face, width, color, emoji="", anchor="lt"):
    glyph = emoji_image(emoji, max(8, getattr(face, "size", 12))) if emoji else None
    inset = glyph.width + (3 if text else 0) if glyph and glyph.width <= width else 0
    while text and draw.textlength(text, font=face) > width - inset:
        text = text[:-1]
    text_width = draw.textlength(text, font=face)
    x, y = xy
    x -= (inset + text_width) * {"l": 0, "m": .5, "r": 1}[anchor[0]]
    if inset:
        top = y - glyph.height / 2 if anchor[1] == "m" else y
        image.alpha_composite(glyph, (round(x), round(top)))
    if text:
        draw.text((x + inset, y), text, font=face, fill=color, anchor="l" + anchor[1])
