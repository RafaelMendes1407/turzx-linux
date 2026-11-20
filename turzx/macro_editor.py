"""GTK controls for choosing emoji and editing a theme's display rules."""

from gi.repository import Gdk, Gtk

from .emojis import EMOJIS
from .gui import box, label
from .macros import COMPARISONS, MAX_MACROS, UNAVAILABLE, Macro
from .metrics import CATEGORIES, is_numeric, spec
from .themes import color


def emoji_menu(on_pick, title="Emojis"):
    content = box(spacing=6)
    for edge in ("top", "bottom", "start", "end"):
        getattr(content, f"set_margin_{edge}")(8)
    popover = Gtk.Popover(child=content)
    palette = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                          min_children_per_line=5, max_children_per_line=5)
    content.append(palette)

    def pick(_, emoji):
        popover.popdown()
        on_pick(emoji)

    for emoji, name in EMOJIS.items():
        button = Gtk.Button(label=emoji, tooltip_text=name)
        button.connect("clicked", pick, emoji)
        palette.insert(button, -1)
    remove = Gtk.Button(label="Remover emoji")
    remove.connect("clicked", pick, "")
    content.append(remove)
    return Gtk.MenuButton(label=title, popover=popover)


def dropdown(options, current):
    widget = Gtk.DropDown.new_from_strings(list(options.values()))
    widget.set_selected(list(options).index(current))
    widget.set_enable_search(True)
    return widget


class MacroRow:
    def __init__(self, editor, item, source_names, rule):
        self.expander = Gtk.Expander(expanded=True)
        self.body = box(spacing=8)
        self.body.set_margin_top(8)
        self.body.set_margin_bottom(12)
        self.expander.set_child(self.body)
        self.sources = source_names
        self.source = dropdown(source_names, rule.source)
        self.add_field("Leitura que dispara a regra", self.source)
        self.comparisons = {key: key for key in COMPARISONS} | {UNAVAILABLE: "Leitura indisponível"}
        self.comparison = dropdown(self.comparisons, rule.comparison)
        self.add_field("Comparação", self.comparison)
        self.threshold = Gtk.Entry(text=str(rule.threshold), max_length=32)
        self.limit_label = label("Limite", "field-label")
        self.limit_box = box(spacing=4)
        self.limit_box.append(self.limit_label)
        self.limit_box.append(self.threshold)
        self.body.append(self.limit_box)

        def update_limit(*_):
            metric = list(self.sources)[self.source.get_selected()] or item.metric
            unit = "B/s" if metric.startswith("network.") else "s" if metric == "system.uptime" else spec(metric).unit
            self.limit_label.set_text(f"Limite ({unit})" if unit else "Limite")
            self.limit_box.set_visible(self.comparison.get_selected() != len(COMPARISONS))

        self.source.connect("notify::selected", update_limit)
        self.comparison.connect("notify::selected", update_limit)
        update_limit()

        self.emoji_options = {None: "Manter emoji", "": "Remover emoji"}
        self.emoji_options.update({emoji: f"{emoji}  {name}" for emoji, name in EMOJIS.items()})
        self.emoji = dropdown(self.emoji_options, rule.emoji)
        self.add_field("Emoji", self.emoji)
        self.colors = {}
        for name, title in (("accent", "Cor da barra / gráfico"), ("color", "Cor do valor"),
                            ("label_color", "Cor do rótulo")):
            current = getattr(rule, name)
            enabled = Gtk.CheckButton(label=title, active=current is not None, hexpand=True)
            rgba = Gdk.RGBA()
            rgba.parse(current or getattr(item, name))
            selector = Gtk.ColorButton(rgba=rgba, use_alpha=False, title=title, sensitive=enabled.get_active())
            enabled.bind_property("active", selector, "sensitive")
            row = box(False, 8)
            row.append(enabled)
            row.append(selector)
            self.body.append(row)
            self.colors[name] = enabled, selector

        actions = box(False, 5)
        for title, command in (("Subir", lambda: editor.move(self, -1)),
                               ("Descer", lambda: editor.move(self, 1)),
                               ("Remover", lambda: editor.remove(self))):
            button = Gtk.Button(label=title)
            button.connect("clicked", lambda _, action=command: action())
            actions.append(button)
        self.body.append(actions)

    def add_field(self, title, widget):
        field = box(spacing=4)
        field.append(label(title, "field-label"))
        field.append(widget)
        self.body.append(field)

    def read(self):
        source = list(self.sources)[self.source.get_selected()]
        comparison = list(self.comparisons)[self.comparison.get_selected()]
        try:
            threshold = 0 if comparison == UNAVAILABLE else float(self.threshold.get_text().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Digite um limite numérico.") from exc
        overrides = {}
        for name, (enabled, selector) in self.colors.items():
            if enabled.get_active():
                rgba = selector.get_rgba()
                overrides[name] = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in (rgba.red, rgba.green, rgba.blue))
        rule = Macro(source, comparison, threshold, list(self.emoji_options)[self.emoji.get_selected()], **overrides)
        rule.validate(color)
        return rule


class MacroEditor(Gtk.Dialog):
    def __init__(self, window, item, keys, save):
        super().__init__(title="Macros de aparência", transient_for=window, modal=True)
        self.set_default_size(540, 650)
        self.item = item
        self.rows = []
        self.sources = {"": "Leitura deste elemento"} if is_numeric(item.metric) else {}
        for key in dict.fromkeys([*keys, *(rule.source for rule in item.macros)]):
            if key and is_numeric(key):
                info = spec(key)
                self.sources[key] = f"{CATEGORIES[info.category]} · {info.label}"

        content = self.get_content_area()
        content.set_spacing(10)
        for edge in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{edge}")(14)
        explanation = label("As regras são avaliadas na ordem da lista. A primeira condição atendida define a aparência.", "muted")
        explanation.set_wrap(True)
        content.append(explanation)
        self.list_box = box(spacing=10)
        self.list_box.set_margin_end(12)
        content.append(Gtk.ScrolledWindow(child=self.list_box, vexpand=True, overlay_scrolling=False,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.add_button_widget = Gtk.Button(label="Adicionar macro")
        self.add_button_widget.connect("clicked", lambda *_: self.add_rule(
            Macro(source=next(iter(self.sources)), threshold=80, accent="#f8ae53")))
        content.append(self.add_button_widget)
        self.error = label("", "feedback")
        self.error.set_wrap(True)
        self.error.set_visible(False)
        content.append(self.error)
        for rule in item.macros:
            self.add_rule(rule, expanded=False)
        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.add_button("Salvar macros", Gtk.ResponseType.ACCEPT).add_css_class("suggested-action")
        self.connect("response", self.respond, save)

    def add_rule(self, rule, expanded=True):
        if len(self.rows) >= MAX_MACROS:
            return
        if rule.source not in self.sources:
            self.sources = {"": "Leitura deste elemento (indisponível)", **self.sources}
        row = MacroRow(self, self.item, self.sources, rule)
        row.expander.set_expanded(expanded)
        self.rows.append(row)
        self.list_box.append(row.expander)
        self.renumber()

    def renumber(self):
        for index, row in enumerate(self.rows, 1):
            row.expander.set_label(f"Regra {index}")
        self.add_button_widget.set_sensitive(len(self.rows) < MAX_MACROS)

    def move(self, row, offset):
        old = self.rows.index(row)
        new = old + offset
        if 0 <= new < len(self.rows):
            self.rows.insert(new, self.rows.pop(old))
            self.list_box.reorder_child_after(row.expander, self.rows[new - 1].expander if new else None)
            self.renumber()

    def remove(self, row):
        self.rows.remove(row)
        self.list_box.remove(row.expander)
        self.renumber()

    def respond(self, _, response, save):
        if response == Gtk.ResponseType.ACCEPT:
            rules = []
            for index, row in enumerate(self.rows, 1):
                try:
                    rules.append(row.read())
                except ValueError as exc:
                    row.expander.set_expanded(True)
                    self.error.set_text(f"Regra {index} · {exc}")
                    self.error.set_visible(True)
                    return
            save(rules)
        self.destroy()
