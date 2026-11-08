"""Portable theme documents and GUI-independent editing operations."""

import base64
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
import io
import json
import math
from pathlib import Path
import re
import uuid

from PIL import Image, ImageOps

from .config import atomic_write, config_dir
from .metrics import CATEGORIES, is_numeric, spec

SIZES = ((480, 320), (320, 480))
STYLES = {"line": "Linha: rótulo + valor", "value": "Destaque: valor grande", "bar": "Valor com barra",
          "chart_line": "Gráfico de linhas", "chart_area": "Gráfico de área", "chart_bars": "Gráfico de colunas"}
CHART_STYLES = {key: name for key, name in STYLES.items() if key.startswith("chart_")}
FONTS = {"sans": "DejaVu Sans", "mono": "DejaVu Mono", "serif": "DejaVu Serif"}


def uid():
    return uuid.uuid4().hex


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) is not None


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Cor inválida; use #RRGGBB.")
    return value


def integer(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{label}: use um inteiro de {lo} a {hi}.")


def text_value(value, limit, label):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label}: use até {limit} caracteres em uma linha.")


@dataclass
class Item:
    id: str = field(default_factory=uid)
    metric: str = "cpu.usage"
    x: int = 10
    y: int = 30
    width: int = 180
    height: int = 30
    label: str = ""
    text: str = "Meu texto"
    style: str = "line"
    font_size: int = 15
    font_family: str = "sans"
    bold: bool = True
    align: str = "right"
    color: str = "#edf4fc"
    label_color: str = "#9cb1c8"
    accent: str = "#6ee7b7"
    show_label: bool = True
    gpu_id: str = "inherit"
    z: int = 0
    chart_window: int = 60
    chart_max: float = 0
    chart_line_width: int = 2
    chart_grid: bool = True


@dataclass
class Container:
    id: str = field(default_factory=uid)
    title: str = "CPU"
    category: str = "cpu"
    x: int = 12
    y: int = 12
    width: int = 220
    height: int = 142
    background: str = "#172436"
    foreground: str = "#a0b8d0"
    border: str = "#2b4055"
    border_width: int = 1
    radius: int = 14
    opacity: int = 255
    title_size: int = 11
    show_title: bool = True
    gpu_id: str = "auto"
    items: list[Item] = field(default_factory=list)
    z: int = 0


@dataclass
class Theme:
    schema: int = 2
    id: str = field(default_factory=uid)
    name: str = "Meu tema"
    width: int = 480
    height: int = 320
    background: str = "#0b1220"
    background_image: str = ""  # embedded, normalized PNG; export has no external paths
    containers: list[Container] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)

    @property
    def size(self):
        return self.width, self.height

    def top_level(self):
        return sorted([*self.containers, *self.items], key=lambda element: element.z)

    def validate(self):
        if type(self.schema) is not int or self.schema != 2:
            raise ValueError("Versão de tema não suportada.")
        if not valid_id(self.id):
            raise ValueError("Identificador de tema inválido.")
        text_value(self.name, 60, "Nome do tema")
        if not self.name.strip():
            raise ValueError("Dê um nome ao tema.")
        if type(self.width) is not int or type(self.height) is not int or self.size not in SIZES:
            raise ValueError("O tema deve ter 480×320 ou 320×480 pixels.")
        color(self.background)
        if not isinstance(self.background_image, str) or len(self.background_image) > 3_000_000:
            raise ValueError("Imagem de fundo inválida ou muito grande.")
        if self.background_image:
            decode_background(self.background_image)
        if not isinstance(self.containers, list) or len(self.containers) > 32:
            raise ValueError("Um tema pode ter até 32 contêineres.")
        ids = {self.id}
        for c in self.containers:
            if not isinstance(c, Container) or not valid_id(c.id) or c.id in ids:
                raise ValueError("Contêiner inválido ou identificador duplicado.")
            ids.add(c.id)
            text_value(c.title, 60, "Título")
            if not isinstance(c.category, str) or c.category not in CATEGORIES:
                raise ValueError("Categoria inválida.")
            integer(c.width, 96, self.width, "Largura do contêiner")
            integer(c.height, 64, self.height, "Altura do contêiner")
            integer(c.x, 0, self.width - c.width, "Posição X")
            integer(c.y, 0, self.height - c.height, "Posição Y")
            for value in (c.background, c.foreground, c.border):
                color(value)
            integer(c.border_width, 0, 6, "Borda")
            integer(c.radius, 0, 48, "Arredondamento")
            integer(c.opacity, 0, 255, "Opacidade")
            integer(c.title_size, 8, 28, "Fonte do título")
            integer(c.z, 0, 4096, "Camada")
            text_value(c.gpu_id, 128, "GPU")
            if type(c.show_title) is not bool:
                raise ValueError("Visibilidade do título inválida.")
            if not isinstance(c.items, list) or len(c.items) > 32:
                raise ValueError("Um contêiner pode ter até 32 informações.")
            for item in c.items:
                if not isinstance(item, Item) or not valid_id(item.id) or item.id in ids:
                    raise ValueError("Informação inválida ou identificador duplicado.")
                ids.add(item.id)
                validate_item(item, c.width, c.height)
        if not isinstance(self.items, list) or len(self.items) > 128:
            raise ValueError("Um tema pode ter até 128 elementos livres.")
        for item in self.items:
            if not isinstance(item, Item) or not valid_id(item.id) or item.id in ids:
                raise ValueError("Elemento livre inválido ou identificador duplicado.")
            ids.add(item.id)
            validate_item(item, self.width, self.height)
        return self


def minimum_size(item):
    return (80, 60) if isinstance(item.style, str) and item.style.startswith("chart_") else (40, 18)


def validate_item(item, width, height):
    spec(item.metric)
    if not isinstance(item.style, str) or item.style not in STYLES or type(item.show_label) is not bool:
        raise ValueError("Estilo de informação inválido.")
    mw, mh = minimum_size(item)
    integer(item.width, mw, width, "Largura da informação")
    integer(item.height, mh, height, "Altura da informação")
    integer(item.x, 0, width - item.width, "Posição X da informação")
    integer(item.y, 0, height - item.height, "Posição Y da informação")
    integer(item.font_size, 8, 64, "Fonte")
    integer(item.z, 0, 4096, "Camada")
    integer(item.chart_window, 10, 300, "Janela do gráfico (segundos)")
    integer(item.chart_line_width, 1, 6, "Espessura da linha")
    if type(item.chart_max) not in (int, float) or not math.isfinite(item.chart_max) or not 0 <= item.chart_max <= 1e15:
        raise ValueError("Escala inválida: use zero para automática ou um máximo positivo.")
    if type(item.chart_grid) is not bool:
        raise ValueError("Grade do gráfico inválida.")
    if item.style in CHART_STYLES and not is_numeric(item.metric):
        raise ValueError("Gráficos precisam de uma informação numérica, como uso, temperatura ou velocidade de rede.")
    text_value(item.label, 60, "Rótulo")
    text_value(item.text, 150, "Texto")
    text_value(item.gpu_id, 128, "GPU")
    for value in (item.color, item.label_color, item.accent):
        color(value)
    if not isinstance(item.font_family, str) or item.font_family not in FONTS or item.align not in ("left", "center", "right") or type(item.bold) is not bool:
        raise ValueError("Fonte ou alinhamento inválido.")


from functools import lru_cache


@lru_cache(maxsize=6)
def decode_background(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != "PNG" or source.width > 960 or source.height > 960:
                raise ValueError("O fundo precisa ser um PNG de até 960×960.")
            return source.convert("RGB")
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Imagem de fundo inválida.") from exc


def encode_background(path, size):
    with Image.open(path) as source:
        image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def from_dict(data):
    def construct(kind, values, children=None):
        if not isinstance(values, dict) or set(values) - {f.name for f in fields(kind)}:
            raise ValueError("Estrutura de tema inválida ou campos desconhecidos.")
        result = deepcopy(values)
        if children:
            key, child_type, grandchildren = children
            if not isinstance(result.get(key, []), list):
                raise ValueError("Lista de componentes inválida.")
            result[key] = [construct(child_type, value, grandchildren) for value in result.get(key, [])]
        try:
            return kind(**result)
        except TypeError as exc:
            raise ValueError("Estrutura de tema inválida.") from exc
    if not isinstance(data, dict):
        raise ValueError("Estrutura de tema inválida.")
    data = deepcopy(data)
    if type(data.get("schema", 1)) is int and data.get("schema", 1) == 1:
        data["schema"] = 2
    free = data.pop("items", [])
    if not isinstance(free, list):
        raise ValueError("Lista de elementos livres inválida.")
    theme = construct(Theme, data, ("containers", Container, ("items", Item, None)))
    theme.items = [construct(Item, item) for item in free]
    return theme.validate()


def themes_dir():
    return config_dir() / "themes"


def theme_path(theme_id):
    if not valid_id(theme_id):
        raise ValueError("Identificador de tema inválido.")
    return themes_dir() / f"{theme_id}.json"


def save_theme(theme, path=None):
    theme.validate()
    atomic_write(path or theme_path(theme.id), json.dumps(asdict(theme), ensure_ascii=False, indent=2).encode())


def read_theme(path):
    path = Path(path)
    if path.stat().st_size > 4_000_000:
        raise ValueError("Tema excede o limite de 4 MB.")
    try:
        return from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Arquivo de tema inválido.") from exc


def load_theme(theme_id):
    return read_theme(theme_path(theme_id))


def list_themes():
    results = []
    for path in themes_dir().glob("*.json"):
        try:
            theme = read_theme(path)
            if path.stem == theme.id:
                results.append((theme.id, theme.name))
        except (ValueError, OSError):
            continue
    return sorted(results, key=lambda entry: entry[1].casefold())


def starter(size=(480, 320)):
    theme = Theme(name="Aurora Studio", width=size[0], height=size[1])
    w, h = (size[0] - 36) // 2, (size[1] - 36) // 2
    categories = [("cpu", "PROCESSADOR", ["cpu.usage", "cpu.temperature", "cpu.cores"]),
                  ("gpu", "PLACA DE VÍDEO", ["gpu.usage", "gpu.temperature", "gpu.memory_percent"]),
                  ("memory", "MEMÓRIA", ["memory.usage", "memory.used", "memory.total"]),
                  ("network", "REDE / SISTEMA", ["network.download", "network.upload", "clock.time"])]
    for index, (category, title, keys) in enumerate(categories):
        c = Container(category=category, title=title, x=12 + (index % 2) * (w + 12),
                      y=12 + (index // 2) * (h + 12), width=w, height=h)
        for row, key in enumerate(keys):
            portrait = size[0] == 320
            c.items.append(Item(metric=key, x=10, y=32 + row * (60 if portrait else 31),
                                width=w - 20, height=54 if portrait else 27,
                                font_size=22 if portrait else 14,
                                style=("bar" if row == 0 and category != "network" else "value") if portrait else "line",
                                align="left" if portrait else "right",
                                accent="#70d9ff" if category == "gpu" else "#6ee7b7"))
        theme.containers.append(c)
    return theme.validate()


def viewport_point(x, y, allocation, canvas):
    """Map a Gtk.Picture point through contain/letterboxing to native panel pixels."""
    aw, ah = allocation
    cw, ch = canvas
    scale = min(aw / cw, ah / ch) if aw > 0 and ah > 0 else 1
    px, py = (x - (aw - cw * scale) / 2) / scale, (y - (ah - ch * scale) / 2) / scale
    return px, py, scale


def contain_rect(obj, width, height, minimum=(40, 18)):
    obj.width = min(width, max(minimum[0], round(obj.width)))
    obj.height = min(height, max(minimum[1], round(obj.height)))
    obj.x = min(width - obj.width, max(0, round(obj.x)))
    obj.y = min(height - obj.height, max(0, round(obj.y)))


def resize_children(container, previous_size):
    sx, sy = container.width / previous_size[0], container.height / previous_size[1]
    for item in container.items:
        item.x, item.y = round(item.x * sx), round(item.y * sy)
        item.width, item.height = round(item.width * sx), round(item.height * sy)
        contain_rect(item, container.width, container.height, minimum_size(item))


class EditorModel:
    def __init__(self, theme):
        self.theme = deepcopy(theme.validate())
        self.selection = None  # (container id or None, optional item id)
        self.undo_stack = []
        self.redo_stack = []
        self.drag_origin = None
        self.saved = deepcopy(self.theme)

    @property
    def dirty(self):
        return self.saved != self.theme

    def checkpoint(self):
        self.undo_stack.append(deepcopy(self.theme))
        self.undo_stack = self.undo_stack[-60:]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(deepcopy(self.theme))
            self.theme = self.undo_stack.pop()
            self.selection = None

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(deepcopy(self.theme))
            self.theme = self.redo_stack.pop()
            self.selection = None

    def selected(self):
        if self.selection:
            if self.selection[0] is None:
                return None, next((i for i in self.theme.items if i.id == self.selection[1]), None)
            for c in self.theme.containers:
                if c.id == self.selection[0]:
                    return c, next((i for i in c.items if i.id == self.selection[1]), None)
        return None, None

    def bounds(self):
        c, item = self.selected()
        if item:
            return ((c.x if c else 0) + item.x, (c.y if c else 0) + item.y, item.width, item.height)
        return (c.x, c.y, c.width, c.height) if c else None

    def hit(self, x, y, containers_only=False):
        for c in reversed(self.theme.top_level()):
            if isinstance(c, Item):
                if not containers_only and c.x <= x <= c.x + c.width and c.y <= y <= c.y + c.height:
                    return None, c.id
                continue
            if c.x <= x <= c.x + c.width and c.y <= y <= c.y + c.height:
                if not containers_only:
                    for item in reversed(c.items):
                        if c.x + item.x <= x <= c.x + item.x + item.width and c.y + item.y <= y <= c.y + item.y + item.height:
                            return c.id, item.id
                return c.id, None
        return None

    def next_z(self):
        objects = self.theme.top_level()
        for index, element in enumerate(objects):
            element.z = index
        return len(objects)

    def add_container(self, category, x=12, y=12):
        if category not in CATEGORIES or len(self.theme.containers) >= 32:
            raise ValueError("Não é possível adicionar esse contêiner.")
        self.checkpoint()
        c = Container(title=CATEGORIES[category].upper(), category=category, x=round(x), y=round(y))
        c.z = self.next_z()
        contain_rect(c, *self.theme.size, minimum=(96, 64))
        self.theme.containers.append(c)
        self.selection = (c.id, None)
        return c

    def add_metric(self, key, x=None, y=None, style=None, free=False):
        spec(key)
        c, _ = self.selected()
        if free:
            c = None
        objects = c.items if c else self.theme.items
        if len(objects) >= (32 if c else 128):
            raise ValueError("Limite de informações atingido.")
        style = style or ("value" if key == "text" else "line")
        if style not in STYLES or (style in CHART_STYLES and not is_numeric(key)):
            raise ValueError("Escolha uma informação numérica para o gráfico.")
        chart = style in CHART_STYLES
        height = 100 if chart else (36 if key == "text" else 26)
        yy = round(y) if y is not None else (max([i.y + i.height + 4 for i in objects] or [30]) if c else 12)
        if c and y is None and yy + height > c.height:
            raise ValueError("Aumente a altura do contêiner ou solte a informação em uma posição livre.")
        self.checkpoint()
        item = Item(metric=key, x=round(x) if x is not None else 10, y=yy,
                    width=c.width - 20 if c else 220, height=height, style=style,
                    gpu_id="inherit" if c else "auto", show_label=key != "text",
                    font_size=24 if key == "text" else 15, align="left" if key == "text" else "right")
        contain_rect(item, c.width if c else self.theme.width, c.height if c else self.theme.height, minimum_size(item))
        if c is None:
            item.z = self.next_z()
        objects.append(item)
        self.selection = (c.id if c else None, item.id)
        return item

    def add_chart(self, style="chart_line", key="cpu.usage", x=None, y=None):
        return self.add_metric(key, x, y, style=style)

    def add_text(self, x=None, y=None):
        return self.add_metric("text", x, y, free=True)

    def delete(self):
        c, item = self.selected()
        if c or item:
            self.checkpoint()
            objects = c.items if c and item else (self.theme.items if item else self.theme.containers)
            objects.remove(item or c)
            self.selection = (c.id, None) if c and item else None

    def duplicate(self):
        c, item = self.selected()
        if c or item:
            objects = c.items if c and item else (self.theme.items if item else self.theme.containers)
            if len(objects) >= (128 if item and not c else 32):
                raise ValueError("Limite de componentes atingido.")
            self.checkpoint()
            clone = deepcopy(item or c)
            clone.id = uid()
            clone.x += 8
            clone.y += 8
            if item:
                contain_rect(clone, c.width if c else self.theme.width, c.height if c else self.theme.height, minimum_size(clone))
                if c is None:
                    clone.z = self.next_z()
                objects.append(clone)
                self.selection = c.id if c else None, clone.id
            else:
                for child in clone.items:
                    child.id = uid()
                contain_rect(clone, *self.theme.size, minimum=(96, 64))
                clone.z = self.next_z()
                self.theme.containers.append(clone)
                self.selection = clone.id, None

    def layer(self, offset):
        c, item = self.selected()
        if c or item:
            target, objects = (item, c.items) if c and item else (item or c, self.theme.top_level())
            pos = objects.index(target)
            new = min(len(objects) - 1, max(0, pos + offset))
            if new != pos:
                self.checkpoint()
                objects.insert(new, objects.pop(pos))
                if not (c and item):
                    for index, element in enumerate(objects):
                        element.z = index

    def set_properties(self, **values):
        c, item = self.selected()
        target = item or c or self.theme
        before = deepcopy(self.theme)
        old_size = (c.width, c.height) if c else None
        try:
            allowed = {f.name for f in fields(type(target))} - {"id", "items", "containers", "schema", "z"}
            if set(values) - allowed:
                raise ValueError("Propriedade inválida.")
            for key, value in values.items():
                setattr(target, key, value)
            if c or item:
                contain_rect(target, c.width if c and item else self.theme.width,
                             c.height if c and item else self.theme.height, minimum_size(item) if item else (96, 64))
                if c and not item and (c.width, c.height) != old_size:
                    resize_children(c, old_size)
            self.theme.validate()
        except Exception:
            self.theme = before
            raise
        if self.theme != before:
            self.undo_stack.append(before)
            self.undo_stack = self.undo_stack[-60:]
            self.redo_stack.clear()

    def resize_canvas(self, size):
        if size not in SIZES:
            raise ValueError("Tamanho de tela inválido.")
        if self.theme.size == size:
            return
        self.checkpoint()
        sx, sy = size[0] / self.theme.width, size[1] / self.theme.height
        self.theme.width, self.theme.height = size
        for c in self.theme.containers:
            old = c.width, c.height
            c.x, c.y = round(c.x * sx), round(c.y * sy)
            c.width, c.height = round(c.width * sx), round(c.height * sy)
            contain_rect(c, *size, minimum=(96, 64))
            resize_children(c, old)
        for item in self.theme.items:
            item.x, item.y = round(item.x * sx), round(item.y * sy)
            item.width, item.height = round(item.width * sx), round(item.height * sy)
            contain_rect(item, *size, minimum_size(item))

    def begin_drag(self):
        self.drag_origin = deepcopy(self.theme)

    def drag(self, dx, dy, resize=False, grid=1):
        if self.drag_origin is None or not self.selection:
            return
        self.theme = deepcopy(self.drag_origin)
        if dx == 0 and dy == 0:
            return
        c, item = self.selected()
        if c is None and item is None:
            return
        target = item or c
        old = (c.width, c.height) if c else None
        pw, ph = (c.width, c.height) if c and item else self.theme.size
        def snap(value):
            return round(value / grid) * grid
        if resize:
            target.width, target.height = snap(target.width + dx), snap(target.height + dy)
            target.width = min(target.width, pw - target.x)
            target.height = min(target.height, ph - target.y)
        else:
            target.x, target.y = snap(target.x + dx), snap(target.y + dy)
        contain_rect(target, pw, ph, minimum_size(item) if item else (96, 64))
        if resize and c and not item:
            resize_children(c, old)

    def finish_drag(self):
        if self.drag_origin is not None and self.theme != self.drag_origin:
            self.undo_stack.append(self.drag_origin)
            self.undo_stack = self.undo_stack[-60:]
            self.redo_stack.clear()
        self.drag_origin = None
