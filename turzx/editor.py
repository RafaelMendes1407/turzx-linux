"""Native GTK 4 theme studio: palette → canvas → nested component inspector."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk
from PIL import Image

from . import service
from .config import Config, load_config, save_config
from .gui import box, label
from .metrics import CATALOG, CATEGORIES, is_numeric, reading, spec
from .sensors import LiveSampler
from .palette import groups as palette_groups
from .theme_render import editor_preview, render_theme
from .themes import (CHART_STYLES, EditorModel, FONTS, Item, SIZES, STYLES, Theme, encode_background, from_dict, list_themes,
                     load_theme, minimum_size, read_theme, save_theme, starter, uid, viewport_point)

EDITOR_CSS = b"""
.studio-sidebar { background: #111a28; padding: 16px; }
.studio-toolbar { background: #141e2c; border-bottom: 1px solid #29384c; padding: 10px 16px; }
.studio-canvas { background: #070c14; }
.studio-section { font-size: 10px; letter-spacing: 1px; color: #bacde2; font-weight: 800; }
.component { background: #1b2a3d; border: 1px solid #2a3b51; padding: 8px 10px; }
.metric { background: transparent; border: 0; padding: 5px 8px; font-size: 12px; }
.metric:hover { background: #23344a; }
.metric label, .component label, .studio-sidebar label { color: #e5effc; }
.category-button { padding: 7px 9px; }
.active-category, .active-category:hover { background: #28524a; border-color: #78e7bd; }
.active-category label { color: #b0ffdc; }
.selected-layer { background: #244c43; color: #9cf4d1; }
.studio-footer { background: #131d2a; border-top: 1px solid #29384c; padding: 10px 16px; }
.inspector-title { font-size: 19px; font-weight: 750; }
.empty { color: #8ca2bc; padding: 12px; }
"""


def clear(parent):
    child = parent.get_first_child()
    while child:
        following = child.get_next_sibling()
        parent.remove(child)
        child = following


def button(text, callback, css=None):
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    if css:
        widget.add_css_class(css)
    return widget


def scroll(child, width=None):
    widget = Gtk.ScrolledWindow(vexpand=True, child=child)
    widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    if width:
        widget.set_size_request(width, -1)
    return widget


def compact_dropdown(widget, width=24):
    def factory():
        result = Gtk.SignalListItemFactory()
        def setup(_, item):
            item.set_child(Gtk.Label(xalign=0, ellipsize=3, max_width_chars=width, width_chars=width))
        result.connect("setup", setup)
        result.connect("bind", lambda _, item: item.get_child().set_text(item.get_item().get_string()))
        return result
    widget.set_factory(factory())
    widget.set_list_factory(factory())
    widget.set_enable_search(True)
    return widget


class StudioWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Turzx Studio · Editor de temas")
        self.set_default_size(1280, 860)
        self.set_size_request(1000, 620)
        provider = Gtk.CssProvider()
        provider.load_from_data(EDITOR_CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.sampler = LiveSampler()
        self.refreshing = False
        self.library_refreshing = False
        self.zoom = 1.5
        self.dragging = False
        self.resize_drag = False
        self.drag_scale = 1
        self.tick_count = 0
        self.catalog_signature = None
        self.last_image = None
        self.inspector_spins = {}
        self.active_category = "cpu"
        error = ""
        try:
            config = load_config()
            if config.mode == "custom":
                try:
                    theme = load_theme(config.custom_theme)
                except FileNotFoundError:
                    if config.custom_theme_data is None:
                        raise
                    theme = from_dict(config.custom_theme_data)
            else:
                theme = starter(config.size)
        except (OSError, ValueError) as exc:
            theme = starter()
            error = str(exc)
        self.model = EditorModel(theme)
        header = Gtk.HeaderBar()
        header.set_title_widget(label("TURZX  /  STUDIO", "brand"))
        header.pack_start(label("EDITOR DE TEMAS", "badge"))
        header.pack_end(button("Configurar tela USB", lambda *_: app.open_settings()))
        self.set_titlebar(header)
        root = box(spacing=0)
        self.set_child(root)

        toolbar = box(False, 8)
        toolbar.add_css_class("studio-toolbar")
        toolbar.append(label("Tema", "muted"))
        self.library = compact_dropdown(Gtk.DropDown.new_from_strings([theme.name]))
        self.library.set_size_request(220, -1)
        self.library.connect("notify::selected", self.on_library)
        toolbar.append(self.library)
        toolbar.append(button("+ Novo", self.new_theme))
        toolbar.append(button("Salvar", self.save))
        toolbar.append(button("Salvar cópia", self.save_copy))
        toolbar.append(button("Importar", self.import_theme))
        toolbar.append(button("Exportar", self.export_theme))
        spacer = box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)
        self.undo_button = button("↶", lambda *_: self.history(False))
        self.undo_button.set_tooltip_text("Desfazer · Ctrl+Z")
        toolbar.append(self.undo_button)
        self.redo_button = button("↷", lambda *_: self.history(True))
        self.redo_button.set_tooltip_text("Refazer · Ctrl+Shift+Z")
        toolbar.append(self.redo_button)
        root.append(toolbar)

        body = box(False, 0)
        body.set_vexpand(True)
        root.append(body)
        left = box(spacing=12)
        left.add_css_class("studio-sidebar")
        left.set_size_request(224, -1)
        left.append(label("BIBLIOTECA", "studio-section"))
        intro = label("Arraste textos, gráficos e leituras\npara o fundo ou para um contêiner.", "muted")
        intro.set_wrap(True)
        left.append(intro)
        tabs = Gtk.Stack()
        tabs.set_vexpand(True)
        switcher = Gtk.StackSwitcher(stack=tabs)
        left.append(switcher)
        components = box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Buscar informação…")
        self.search.connect("search-changed", lambda *_: self.rebuild_palette())
        components.append(self.search)
        tools_row = box(False, 6)
        text_button = button("＋ Texto livre", lambda *_: self.add_text(), "component")
        self.draggable(text_button, "free:text")
        tools_row.append(text_button)
        chart_button = button("＋ Gráfico", lambda *_: self.add_chart(), "component")
        self.draggable(chart_button, "chart:chart_line")
        tools_row.append(chart_button)
        components.append(tools_row)
        categories = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                 min_children_per_line=2, max_children_per_line=2,
                                 row_spacing=5, column_spacing=5)
        self.category_buttons = {}
        for key, name in CATEGORIES.items():
            chip = button("Sistema" if key == "system" else name, lambda _, choice=key: self.choose_category(choice), "category-button")
            categories.insert(chip, -1)
            self.category_buttons[key] = chip
        components.append(categories)
        self.palette = box(spacing=10)
        components.append(scroll(self.palette))
        tabs.add_titled(components, "components", "Componentes")
        self.layers = box(spacing=3)
        tabs.add_titled(scroll(self.layers), "layers", "Camadas")
        left.append(tabs)
        body.append(left)

        center = box(spacing=0)
        center.set_hexpand(True)
        center.add_css_class("studio-canvas")
        canvas_toolbar = box(False, 10)
        canvas_toolbar.add_css_class("studio-toolbar")
        self.dimension = Gtk.DropDown.new_from_strings(["Paisagem · 480 × 320", "Retrato · 320 × 480"])
        self.dimension.set_selected(SIZES.index(theme.size))
        self.dimension.connect("notify::selected", self.change_size)
        canvas_toolbar.append(self.dimension)
        self.grid = Gtk.CheckButton(label="Encaixar em 8 px", active=True)
        self.grid.set_tooltip_text("Os pontos de alinhamento ficam sempre visíveis. Esta opção ativa apenas o encaixe.")
        self.grid.connect("toggled", lambda *_: self.paint())
        canvas_toolbar.append(self.grid)
        self.zoom_select = Gtk.DropDown.new_from_strings(["100%", "150%", "200%"])
        self.zoom_select.set_selected(1)
        self.zoom_select.connect("notify::selected", self.change_zoom)
        canvas_toolbar.append(self.zoom_select)
        center.append(canvas_toolbar)
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(False)
        self.picture.set_halign(Gtk.Align.CENTER)
        self.picture.set_valign(Gtk.Align.CENTER)
        self.picture.set_focusable(True)
        self.picture.set_margin_top(24)
        self.picture.set_margin_bottom(24)
        self.picture.set_margin_start(24)
        self.picture.set_margin_end(24)
        self.canvas_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True, child=self.picture)
        center.append(self.canvas_scroll)
        self.canvas_caption = label("Arraste pelo título para mover o contêiner; use o canto para redimensionar.", "muted")
        self.canvas_caption.set_wrap(True)
        self.canvas_caption.set_margin_start(16)
        self.canvas_caption.set_margin_end(16)
        self.canvas_caption.set_margin_bottom(12)
        center.append(self.canvas_caption)
        body.append(center)

        inspector_outer = box(spacing=8)
        inspector_outer.add_css_class("studio-sidebar")
        inspector_outer.set_size_request(270, -1)
        inspector_outer.append(label("PROPRIEDADES", "studio-section"))
        self.inspector = box(spacing=12)
        inspector_outer.append(scroll(self.inspector))
        body.append(inspector_outer)

        footer = box(False, 12)
        footer.add_css_class("studio-footer")
        self.feedback = label(error or "Monte sua tela. Salvar guarda o tema; Aplicar envia ao painel USB.", "feedback")
        self.feedback.set_hexpand(True)
        self.feedback.set_wrap(True)
        self.feedback.set_max_width_chars(80)
        footer.append(self.feedback)
        footer.append(button("Parar painel", self.stop))
        footer.append(button("Aplicar na tela", self.apply, "suggested-action"))
        root.append(footer)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self.drag_begin)
        drag.connect("drag-update", self.drag_update)
        drag.connect("drag-end", self.drag_end)
        self.picture.add_controller(drag)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self.canvas_click)
        self.picture.add_controller(click)
        click.group(drag)
        drop = Gtk.DropTarget.new(str, Gdk.DragAction.COPY)
        drop.connect("drop", self.drop)
        self.picture.add_controller(drop)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_press)
        self.picture.add_controller(keys)
        self.rebuild_palette()
        self.refresh_library()
        self.refresh()
        self.timer = GLib.timeout_add(500, self.tick)
        self.connect("close-request", self.on_close)
        self.allow_close = False

    def show_message(self, message):
        self.feedback.set_text(message)

    def all_metrics(self):
        keys = list(CATALOG)
        snapshot = self.sampler.latest
        if snapshot:
            keys += [f"cpu.core.{index}" for index in range(len(snapshot.per_core))]
        return keys

    def draggable(self, widget, payload):
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.COPY)
        source.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(payload))
        widget.add_controller(source)
        widget.set_tooltip_text("Arraste para a tela ou clique para adicionar.")

    def choose_category(self, category):
        self.active_category = category
        self.search.set_text("")
        self.rebuild_palette()

    def rebuild_palette(self):
        if not hasattr(self, "palette"):
            return
        query = self.search.get_text().casefold()
        for key, chip in self.category_buttons.items():
            if key == self.active_category:
                chip.add_css_class("active-category")
            else:
                chip.remove_css_class("active-category")
        clear(self.palette)
        for category, keys in palette_groups(self.all_metrics(), self.active_category, query).items():
            title = CATEGORIES[category]
            section = box(spacing=4)
            add = button(f"＋ Contêiner {title}", lambda _, cat=category: self.add_container(cat), "component")
            self.draggable(add, "container:" + category)
            section.append(add)
            core_rows = box(spacing=4)
            for key in keys:
                row = button("⋮⋮  " + spec(key).label, lambda _, metric=key: self.add_metric(metric), "metric")
                row.get_child().set_xalign(0)
                self.draggable(row, "metric:" + key)
                (core_rows if key.startswith("cpu.core.") else section).append(row)
            if core_rows.get_first_child():
                threads = Gtk.Expander(label="Uso por thread lógica", expanded=bool(query))
                threads.set_child(core_rows)
                section.append(threads)
            if query:
                self.palette.append(label(title, "studio-section"))
            self.palette.append(section)

    def refresh_library(self):
        self.library_refreshing = True
        entries = list_themes()
        self.library_ids = [None] + [entry[0] for entry in entries]
        self.library.set_model(Gtk.StringList.new(["Rascunho · " + self.model.theme.name] + [entry[1] for entry in entries]))
        current = self.model.theme.id
        self.library.set_selected(self.library_ids.index(current) if current in self.library_ids else 0)
        self.library_refreshing = False

    def on_library(self, *_):
        if self.library_refreshing or not hasattr(self, "library_ids"):
            return
        index = self.library.get_selected()
        if index >= len(self.library_ids):
            return
        theme_id = self.library_ids[index]
        if theme_id and theme_id != self.model.theme.id:
            self.confirm_discard(lambda: self.open_theme(theme_id))

    def open_theme(self, theme_id):
        try:
            self.model = EditorModel(load_theme(theme_id))
            self.refresh_library()
            self.refresh()
        except (ValueError, OSError) as exc:
            self.show_message(str(exc))

    def confirm_discard(self, action):
        if not self.model.dirty:
            action()
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text="Salvar as alterações do tema?",
                                   secondary_text="Você pode salvar antes de continuar ou descartar apenas as alterações não salvas.")
        dialog.add_button("Continuar editando", Gtk.ResponseType.CANCEL)
        dialog.add_button("Descartar alterações", Gtk.ResponseType.REJECT)
        dialog.add_button("Salvar e continuar", Gtk.ResponseType.ACCEPT)
        def response(widget, code):
            widget.destroy()
            if code == Gtk.ResponseType.REJECT or (code == Gtk.ResponseType.ACCEPT and self.save()):
                action()
            else:
                self.refresh_library()
        dialog.connect("response", response)
        dialog.present()

    def new_theme(self, *_):
        def choose():
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                       text="Como você quer começar?",
                                       secondary_text="Uma tela vazia para criar do zero ou um modelo com CPU, GPU, memória e rede.")
            dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
            dialog.add_button("Tela vazia", 10)
            dialog.add_button("Modelo CPU + GPU", 11)
            def response(widget, code):
                widget.destroy()
                if code in (10, 11):
                    size = self.model.theme.size
                    theme = Theme(width=size[0], height=size[1]) if code == 10 else starter(size)
                    self.model = EditorModel(theme)
                    self.refresh_library()
                    self.refresh()
            dialog.connect("response", response)
            dialog.present()
        self.confirm_discard(choose)

    def save(self, *_):
        try:
            save_theme(self.model.theme)
            self.model.saved = deepcopy(self.model.theme)
            self.refresh_library()
            self.refresh(False)
            self.show_message(f'Tema “{self.model.theme.name}” salvo. Use Aplicar para enviá-lo à tela.')
            settings = getattr(self.get_application(), "settings_window", None)
            if settings:
                settings.refresh_custom_themes()
            return True
        except (ValueError, OSError) as exc:
            self.show_message(str(exc))
            return False

    def save_copy(self, *_):
        theme = deepcopy(self.model.theme)
        theme.id = uid()
        theme.name = theme.name[:52] + " · cópia"
        self.model = EditorModel(theme)
        self.save()
        self.refresh()

    def choose_file(self, title, action, callback, name=None, images=False):
        dialog = Gtk.FileChooserNative(title=title, transient_for=self, action=action,
                                       accept_label="Salvar" if action == Gtk.FileChooserAction.SAVE else "Abrir", cancel_label="Cancelar")
        filter_ = Gtk.FileFilter()
        filter_.set_name("Imagens" if images else "Tema Turzx (.json)")
        if images:
            for mime in ("image/png", "image/jpeg", "image/webp", "image/bmp"):
                filter_.add_mime_type(mime)
        else:
            filter_.add_pattern("*.json")
        dialog.add_filter(filter_)
        if name:
            dialog.set_current_name(name)
        def response(widget, code):
            if code == Gtk.ResponseType.ACCEPT:
                path = widget.get_file().get_path()
                try:
                    if not path:
                        raise ValueError("Escolha um arquivo local.")
                    callback(Path(path))
                except (ValueError, OSError, Image.DecompressionBombError) as exc:
                    self.show_message(str(exc))
            widget.destroy()
        dialog.connect("response", response)
        dialog.show()

    def import_theme(self, *_):
        def imported(path):
            theme = read_theme(path)
            theme.id = uid()  # importing never overwrites an existing theme
            def use():
                self.model = EditorModel(theme)
                self.save()
                self.refresh()
            self.confirm_discard(use)
        self.choose_file("Importar tema", Gtk.FileChooserAction.OPEN, imported)

    def export_theme(self, *_):
        self.choose_file("Exportar tema", Gtk.FileChooserAction.SAVE,
                         lambda path: self.export_to(path), "meu-tema-turzx.json")

    def export_to(self, path):
        save_theme(self.model.theme, path)
        self.show_message(f"Tema exportado para {path}. O fundo também está incluído.")

    def apply(self, *_):
        if not self.save():
            return
        try:
            config = load_config()
            rotation = config.rotation if config.size == self.model.theme.size else (90 if self.model.theme.width == 480 else 0)
            save_config(replace(config, mode="custom", custom_theme=self.model.theme.id,
                                custom_theme_data=asdict(self.model.theme), rotation=rotation))
            service.start()
            service.request("RELOAD")
            self.show_message("Tema aplicado. " + ("A tela está apagada; ative-a em Configurar tela USB." if not config.screen_on else "Acompanhe a conexão abaixo da tela."))
            settings = getattr(self.get_application(), "settings_window", None)
            if settings:
                settings.select_custom_theme(self.model.theme.id, rotation)
        except (OSError, ValueError) as exc:
            self.show_message(str(exc))

    def stop(self, *_):
        self.show_message("Parando painel…" if service.request("STOP") else "O painel já está parado.")

    def add_container(self, category, x=None, y=None):
        try:
            offset = 12 + len(self.model.theme.containers) % 6 * 16
            self.model.add_container(category, offset if x is None else x, offset if y is None else y)
            self.refresh()
            self.show_message("Contêiner criado. Arraste informações para dentro dele ou clique na biblioteca.")
        except ValueError as exc:
            self.show_message(str(exc))

    def add_metric(self, metric, x=None, y=None):
        try:
            self.model.add_metric(metric, x, y)
            self.refresh()
        except ValueError as exc:
            self.show_message(str(exc))

    def add_text(self, x=None, y=None):
        self.perform(lambda: self.model.add_text(x, y))

    def add_chart(self, style="chart_line", x=None, y=None):
        self.perform(lambda: self.model.add_chart(style, x=x, y=y))

    def point(self, x, y):
        return viewport_point(x, y, (self.picture.get_width(), self.picture.get_height()), self.model.theme.size)

    def drop(self, _, payload, x, y):
        if not isinstance(payload, str):
            return False
        x, y, _ = self.point(x, y)
        if not (0 <= x < self.model.theme.width and 0 <= y < self.model.theme.height):
            return False
        if payload.startswith("container:") and payload[10:] in CATEGORIES:
            self.add_container(payload[10:], x, y)
        elif payload == "free:text":
            self.add_text(x, y)
        elif payload.startswith("chart:") and payload[6:] in CHART_STYLES:
            self.model.selection = self.model.hit(x, y, containers_only=True)
            c, _ = self.model.selected()
            self.add_chart(payload[6:], x - c.x if c else x, y - c.y if c else y)
        elif payload.startswith("metric:"):
            try:
                spec(payload[7:])
            except ValueError:
                return False
            self.model.selection = self.model.hit(x, y, containers_only=True)
            c, _ = self.model.selected()
            self.add_metric(payload[7:], x - c.x if c else x, y - c.y if c else y)
        else:
            return False
        self.picture.grab_focus()
        return True

    def drag_begin(self, _, x, y):
        self.picture.grab_focus()
        x, y, self.drag_scale = self.point(x, y)
        rect = self.model.bounds()
        self.resize_drag = bool(rect and abs(x - (rect[0] + rect[2])) <= 12 and abs(y - (rect[1] + rect[3])) <= 12)
        if not self.resize_drag:
            self.model.selection = self.model.hit(x, y)
        self.dragging = bool(self.model.selection)
        self.model.begin_drag()
        self.refresh()

    def canvas_click(self, _, __, x, y):
        self.picture.grab_focus()
        x, y, _ = self.point(x, y)
        rect = self.model.bounds()
        on_handle = bool(rect and abs(x - (rect[0] + rect[2])) <= 12 and abs(y - (rect[1] + rect[3])) <= 12)
        if not on_handle:
            self.model.selection = self.model.hit(x, y)
        self.refresh()

    def drag_update(self, _, dx, dy):
        if self.dragging:
            self.model.drag(dx / self.drag_scale, dy / self.drag_scale, self.resize_drag, 8 if self.grid.get_active() else 1)
            self.refresh(False)

    def drag_end(self, *_):
        self.model.finish_drag()
        self.dragging = False
        self.refresh()

    def change_size(self, *_):
        if not self.refreshing:
            self.model.resize_canvas(SIZES[self.dimension.get_selected()])
            self.refresh()

    def change_zoom(self, *_):
        self.zoom = (1, 1.5, 2)[self.zoom_select.get_selected()]
        self.paint()

    def history(self, redo):
        self.model.redo() if redo else self.model.undo()
        self.refresh()

    def key_press(self, _, key, __, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and key in (Gdk.KEY_z, Gdk.KEY_Z):
            self.history(shift)
        elif ctrl and key in (Gdk.KEY_s, Gdk.KEY_S):
            self.save()
        elif ctrl and key in (Gdk.KEY_d, Gdk.KEY_D):
            self.perform(self.model.duplicate)
        elif key in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.perform(self.model.delete)
        elif key == Gdk.KEY_Escape:
            self.model.selection = None
            self.refresh()
        elif key in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            delta = 8 if shift else 1
            dx = delta * ((key == Gdk.KEY_Right) - (key == Gdk.KEY_Left))
            dy = delta * ((key == Gdk.KEY_Down) - (key == Gdk.KEY_Up))
            self.model.begin_drag()
            self.model.drag(dx, dy)
            self.model.finish_drag()
            self.refresh()
        else:
            return False
        return True

    def perform(self, operation):
        try:
            operation()
            self.refresh()
        except (ValueError, OSError) as exc:
            self.show_message(str(exc))

    def refresh(self, inspector=True):
        self.refreshing = True
        self.dimension.set_selected(SIZES.index(self.model.theme.size))
        self.undo_button.set_sensitive(bool(self.model.undo_stack))
        self.redo_button.set_sensitive(bool(self.model.redo_stack))
        self.set_title(("● " if self.model.dirty else "") + self.model.theme.name + " · Turzx Studio")
        if inspector:
            self.build_inspector()
            self.build_layers()
        else:
            c, item = self.model.selected()
            target = item or c or self.model.theme
            for key, spin in self.inspector_spins.items():
                spin.set_value(getattr(target, key))
        self.refreshing = False
        self.paint()

    def paint(self):
        if not hasattr(self, "picture"):
            return
        w, h = self.model.theme.size
        self.picture.set_size_request(round(w * self.zoom), round(h * self.zoom))
        snapshot = self.sampler.latest
        if snapshot is None:
            if self.sampler.error:
                self.show_message("Não foi possível ler os sensores: " + self.sampler.error)
            return
        try:
            self.last_image = render_theme(self.model.theme, snapshot)
            preview = editor_preview(self.model, snapshot, self.grid.get_active())
            texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(preview.tobytes()), w * 3)
            self.picture.set_paintable(texture)
        except (ValueError, OSError) as exc:
            self.show_message(str(exc))

    def tick(self):
        self.paint()
        snapshot = self.sampler.latest
        if snapshot:
            signature = (len(snapshot.per_core), tuple(gpu.id for gpu in snapshot.gpus))
            if signature != self.catalog_signature:
                self.catalog_signature = signature
                self.rebuild_palette()
        self.tick_count += 1
        state = service.status()
        count = len(self.sampler.latest.gpus) if self.sampler.latest else 0
        self.canvas_caption.set_text(f"{count} GPU(s) detectada(s)  ·  {state['message']}\nArraste pelo título; redimensione pelo canto. Clique no fundo para editar o tema.")
        return True

    def build_layers(self):
        clear(self.layers)
        if not self.model.theme.containers and not self.model.theme.items:
            self.layers.append(label("Seu tema ainda está vazio.", "empty"))
        for c in reversed(self.model.theme.top_level()):
            rows = ([((None, c.id), ("▥  " if c.style in CHART_STYLES else "T  ") +
                     (c.text if c.metric == "text" else c.label or spec(c.metric).label))] if isinstance(c, Item) else
                    [((c.id, None), "▣  " + c.title)] + [((c.id, i.id), "    ↳ " + (i.label or spec(i.metric).label)) for i in c.items])
            for selected, title in rows:
                widget = button(title, lambda _, choice=selected: self.select(choice),
                                "selected-layer" if selected == self.model.selection else "metric")
                widget.get_child().set_xalign(0)
                widget.get_child().set_ellipsize(3)
                widget.get_child().set_max_width_chars(24)
                self.layers.append(widget)

    def select(self, choice):
        self.model.selection = choice
        self.refresh()

    def build_inspector(self):
        clear(self.inspector)
        self.inspector_spins = {}
        c, item = self.model.selected()
        target = item or c or self.model.theme
        context = (self.model.theme.id, self.model.selection)
        def update(key, value, rebuild=False):
            if self.refreshing or context != (self.model.theme.id, self.model.selection):
                return
            try:
                self.model.set_properties(**{key: value})
                self.refresh(rebuild)
            except (ValueError, OSError) as exc:
                self.show_message(str(exc))

        def field(title, widget):
            group = box(spacing=4)
            group.append(label(title, "field-label"))
            group.append(widget)
            self.inspector.append(group)

        def entry(title, key, limit=60):
            widget = Gtk.Entry(text=getattr(target, key), max_length=limit)
            widget.connect("activate", lambda *_: update(key, widget.get_text()))
            focus = Gtk.EventControllerFocus()
            focus.connect("leave", lambda *_: update(key, widget.get_text()))
            widget.add_controller(focus)
            field(title, widget)

        def number(title, key, low, high):
            widget = Gtk.SpinButton.new_with_range(low, high, 1)
            widget.set_value(getattr(target, key))
            widget.connect("value-changed", lambda *_: update(key, widget.get_value_as_int()))
            self.inspector_spins[key] = widget
            field(title, widget)

        def toggle(title, key):
            widget = Gtk.CheckButton(label=title, active=getattr(target, key))
            widget.connect("toggled", lambda *_: update(key, widget.get_active()))
            self.inspector.append(widget)

        def color(title, key):
            rgba = Gdk.RGBA()
            rgba.parse(getattr(target, key))
            widget = Gtk.ColorButton(rgba=rgba, use_alpha=False, title=title)
            def changed(*_):
                value = widget.get_rgba()
                update(key, "#%02x%02x%02x" % tuple(round(component * 255) for component in (value.red, value.green, value.blue)))
            widget.connect("color-set", changed)
            field(title, widget)

        if c is None and item is None:
            self.inspector.append(label("Seu tema", "inspector-title"))
            entry("Nome", "name")
            color("Cor de fundo", "background")
            self.inspector.append(button("Escolher imagem de fundo…", self.background_image))
            if self.model.theme.background_image:
                self.inspector.append(button("Remover imagem de fundo", lambda *_: update("background_image", "", True)))
            help_ = label("Selecione um contêiner ou uma informação para editar.\n\nArraste a biblioteca para a tela. A grade ajuda a alinhar.\n\nCtrl+Z: desfazer\nCtrl+Shift+Z: refazer\nDelete: excluir\nSetas: mover 1 px\nShift+setas: mover 8 px", "muted")
            help_.set_wrap(True)
            self.inspector.append(help_)
            return
        self.inspector.append(label(("Elemento livre" if not c else "Informação") if item else "Contêiner", "inspector-title"))
        if item:
            if c:
                self.inspector.append(button("↑ Selecionar contêiner", lambda *_: self.select((c.id, None))))
            keys = self.all_metrics()
            if item.style in CHART_STYLES:
                keys = [key for key in keys if is_numeric(key)]
            if item.metric not in keys:
                keys.append(item.metric)
            source = compact_dropdown(Gtk.DropDown.new_from_strings([CATEGORIES[spec(k).category] + " · " + spec(k).label for k in keys]))
            source.set_selected(keys.index(item.metric))
            source.connect("notify::selected", lambda *_: update("metric", keys[source.get_selected()], True))
            field("Informação", source)
            entry("Rótulo (vazio = automático)", "label")
            if item.metric == "text":
                entry("Texto", "text", 150)
            styles = {key: name for key, name in STYLES.items() if key not in CHART_STYLES or is_numeric(item.metric)}
            style = compact_dropdown(Gtk.DropDown.new_from_strings(list(styles.values())))
            style.set_selected(list(styles).index(item.style))
            style.connect("notify::selected", lambda *_: update("style", list(styles)[style.get_selected()], True))
            field("Visualização", style)
            if item.style in CHART_STYLES:
                number("Histórico (segundos)", "chart_window", 10, 300)
                maximum = Gtk.SpinButton.new_with_range(0, 1e15, 1)
                maximum.set_digits(1)
                maximum.set_value(item.chart_max)
                maximum.connect("value-changed", lambda *_: update("chart_max", maximum.get_value()))
                self.inspector_spins["chart_max"] = maximum
                unit = "B/s" if item.metric.startswith("network.") else ("s" if item.metric == "system.uptime" else spec(item.metric).unit)
                field(f"Máximo da escala{(' · ' + unit) if unit else ''} (0 = automático)", maximum)
                toggle("Grade interna do gráfico", "chart_grid")
                number("Espessura da linha (px)", "chart_line_width", 1, 6)
            if item.metric.startswith("gpu."):
                gpus = self.sampler.latest.gpus if self.sampler.latest else []
                ids = (["inherit"] if c else []) + ["auto"] + [gpu.id for gpu in gpus]
                names = (["Usar a GPU do contêiner"] if c else []) + ["Automática"] + [gpu.name for gpu in gpus]
                if item.gpu_id not in ids:
                    ids.append(item.gpu_id)
                    names.append("GPU selecionada · indisponível")
                selector = compact_dropdown(Gtk.DropDown.new_from_strings(names))
                selector.set_selected(ids.index(item.gpu_id))
                selector.connect("notify::selected", lambda *_: update("gpu_id", ids[selector.get_selected()]))
                field("Placa de vídeo", selector)
            toggle("Mostrar rótulo", "show_label")
            fonts = Gtk.DropDown.new_from_strings(list(FONTS.values()))
            fonts.set_selected(list(FONTS).index(item.font_family))
            fonts.connect("notify::selected", lambda *_: update("font_family", list(FONTS)[fonts.get_selected()]))
            field("Fonte", fonts)
            toggle("Negrito", "bold")
            alignment = Gtk.DropDown.new_from_strings(["Esquerda", "Centro", "Direita"])
            alignment.set_selected(["left", "center", "right"].index(item.align))
            alignment.connect("notify::selected", lambda *_: update("align", ["left", "center", "right"][alignment.get_selected()]))
            field("Alinhamento do destaque / texto", alignment)
            number("Tamanho da fonte", "font_size", 8, 64)
            color("Cor do valor", "color")
            color("Cor do rótulo", "label_color")
            color("Cor do gráfico / barra", "accent")
            snapshot = self.sampler.latest
            if snapshot:
                gpu_id = (c.gpu_id if c else "auto") if item.gpu_id == "inherit" else item.gpu_id
                value = reading(item.metric, snapshot, gpu_id, item.text)
                live = label("Agora: " + value.text if value.available else "Sensor indisponível nesta seleção; aparecerá N/D.", "muted")
                live.set_wrap(True)
                self.inspector.append(live)
        else:
            entry("Título", "title")
            toggle("Mostrar título", "show_title")
            if c.category == "gpu" or any(i.metric.startswith("gpu.") for i in c.items):
                gpus = self.sampler.latest.gpus if self.sampler.latest else []
                ids = ["auto"] + [gpu.id for gpu in gpus]
                names = ["Automática · primeira detectada"] + [gpu.name for gpu in gpus]
                if c.gpu_id not in ids:
                    ids.append(c.gpu_id)
                    names.append("GPU selecionada · indisponível")
                selector = compact_dropdown(Gtk.DropDown.new_from_strings(names))
                selector.set_selected(ids.index(c.gpu_id))
                selector.connect("notify::selected", lambda *_: update("gpu_id", ids[selector.get_selected()]))
                field("Placa de vídeo deste contêiner", selector)
            color("Fundo do contêiner", "background")
            color("Cor do título", "foreground")
            color("Cor da borda", "border")
            number("Espessura da borda (px)", "border_width", 0, 6)
            number("Cantos arredondados (px)", "radius", 0, 48)
            number("Fonte do título", "title_size", 8, 28)
            opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            opacity.set_value(c.opacity / 255 * 100)
            opacity.set_draw_value(True)
            opacity.set_digits(0)
            opacity.connect("value-changed", lambda *_: update("opacity", round(opacity.get_value() / 100 * 255)))
            field("Opacidade do fundo (%)", opacity)
        self.inspector.append(label("POSIÇÃO E TAMANHO · PX", "studio-section"))
        min_width, min_height = minimum_size(item) if item else (96, 64)
        for title, key, low, high in (("X", "x", 0, 480), ("Y", "y", 0, 480),
                                      ("Largura", "width", min_width, 480),
                                      ("Altura", "height", min_height, 480)):
            number(title, key, low, high)
        self.inspector.append(button("Trazer para frente", lambda *_: self.perform(lambda: self.model.layer(1))))
        self.inspector.append(button("Enviar para trás", lambda *_: self.perform(lambda: self.model.layer(-1))))
        self.inspector.append(button("Duplicar", lambda *_: self.perform(self.model.duplicate)))
        self.inspector.append(button("Excluir", lambda *_: self.perform(self.model.delete)))

    def background_image(self, *_):
        def chosen(path):
            self.model.selection = None
            self.model.set_properties(background_image=encode_background(path, self.model.theme.size))
            self.refresh()
        self.choose_file("Imagem de fundo", Gtk.FileChooserAction.OPEN, chosen, images=True)

    def on_close(self, *_):
        if not self.allow_close and self.model.dirty:
            def close():
                self.allow_close = True
                self.close()
            self.confirm_discard(close)
            return True
        GLib.source_remove(self.timer)
        self.sampler.close()
        return False
