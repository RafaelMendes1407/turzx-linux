"""GTK 4 desktop configuration, in Brazilian Portuguese."""

import json
from dataclasses import asdict
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk
from PIL import Image, ImageOps

from . import service
from .config import Config, MODES, ROTATIONS, THEMES, config_dir, load_config, save_config
from .desktop import autostart_path, set_autostart
from .device import discover
from .render import render
from .sensors import LiveSampler
from .themes import list_themes, load_theme

CSS = b"""
window { background: #0c111b; color: #e7edf5; }
window label, button label, dropdown label, checkbutton label, expander label,
popover label, listview label, entry text, spinbutton text, textview text, scale value { color: #edf4fc; }
entry, spinbutton, dropdown > button { background: #1b293c; color: #edf4fc; border: 1px solid #52677f; }
popover contents, listview { background: #172337; color: #edf4fc; }
listview row { background: #172337; color: #edf4fc; }
listview row:selected, selection { background: #315d81; color: #ffffff; }
button { background: #24354c; color: #edf4fc; border: 1px solid #425874; }
button:hover { background: #304661; }
button:disabled, button:disabled label { color: #a7b7cb; }
entry placeholder, .dim-label { color: #b2c2d6; }
headerbar { background: #101722; border-bottom: 1px solid #253044; }
.brand { font-size: 15px; font-weight: 800; letter-spacing: 2px; }
.badge { background: #1c302d; color: #78dfbc; border-radius: 12px; padding: 4px 10px; font-size: 10px; }
.sidebar { background: #111a28; border-right: 1px solid #253044; padding: 20px; }
.heading { font-size: 24px; font-weight: 800; }
.section { font-size: 15px; font-weight: 700; }
.muted { color: #9baec4; font-size: 12px; }
.field-label { color: #c4d1e2; font-size: 12px; }
.preview-shell { background: #05080e; border: 2px solid #2b374a; border-radius: 22px; padding: 20px; }
.status { background: #141f2d; border-radius: 12px; padding: 14px; }
.connected { color: #79e7be; }
.actions { border-top: 1px solid #253044; padding: 14px 22px; background: #101722; }
button { border-radius: 8px; padding: 8px 12px; }
button.suggested-action { background: #73dfb7; color: #0b241c; font-weight: 700; }
button.suggested-action label { color: #0b241c; }
entry, dropdown, spinbutton { border-radius: 7px; min-height: 32px; }
scale highlight { background: #73dfb7; }
switch:checked { background: #419d7d; }
.feedback { font-size: 12px; color: #b9ccdf; }
"""


def label(text, css=None):
    widget = Gtk.Label(label=text, xalign=0)
    if css:
        widget.add_css_class(css)
    return widget


def box(vertical=True, spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Turzx Linux")
        self.set_default_size(1040, 820)
        self.sampler = LiveSampler()
        self.last_image = None
        self.poll_count = 0
        try:
            self.config = load_config()
            initial_error = ""
        except (ValueError, OSError) as exc:
            self.config = Config()
            initial_error = str(exc)
        self.image_path = self.config.image_path
        header = Gtk.HeaderBar()
        header.set_title_widget(label("TURZX  /  LINUX", "brand"))
        header.pack_start(label("3,5″ USB", "badge"))
        editor_button = Gtk.Button(label="Editor de temas")
        editor_button.connect("clicked", lambda *_: app.do_activate())
        header.pack_end(editor_button)
        self.set_titlebar(header)
        root = box(spacing=0)
        self.set_child(root)
        body = box(False, 0)
        body.set_vexpand(True)
        root.append(body)
        sidebar = box(spacing=15)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(300, -1)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(sidebar)
        body.append(scroll)
        sidebar.append(label("Configuração", "section"))
        sidebar.append(label("Personalize seu pequeno painel.", "muted"))
        self.mode = self.dropdown(sidebar, "O que mostrar", MODES, self.config.mode)
        self.custom = Gtk.DropDown.new_from_strings(["Crie um tema no editor"])
        self.field(sidebar, "Tema criado no editor", self.custom)
        self.refresh_custom_themes()
        self.title_entry = Gtk.Entry(text=self.config.title, max_length=28)
        self.field(sidebar, "Título", self.title_entry)
        self.theme = self.dropdown(sidebar, "Tema", THEMES, self.config.theme)
        self.rotation = self.dropdown(sidebar, "Orientação", ROTATIONS, self.config.rotation)
        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.brightness.set_value(self.config.brightness)
        self.brightness.set_draw_value(True)
        self.brightness.set_digits(0)
        self.field(sidebar, "Brilho (%)", self.brightness)
        self.interval = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.interval.set_value(self.config.interval)
        self.field(sidebar, "Atualizar a cada (segundos)", self.interval)
        self.image_button = Gtk.Button(label="Escolher imagem…")
        self.image_button.connect("clicked", self.choose_image)
        self.field(sidebar, "Imagem personalizada", self.image_button)
        self.image_label = label(Path(self.image_path).name if self.image_path else "PNG, JPEG, WebP ou BMP", "muted")
        self.image_label.set_ellipsize(3)
        self.image_label.set_max_width_chars(28)
        sidebar.append(self.image_label)
        self.port_entry = Gtk.Entry(text=self.config.port, placeholder_text="auto ou /dev/ttyACM0")
        self.field(sidebar, "Porta USB", self.port_entry)
        self.screen_switch = self.switch_row(sidebar, "Tela acesa", self.config.screen_on)
        self.autostart = self.switch_row(sidebar, "Iniciar ao entrar no Linux", autostart_path().exists())

        content = box(spacing=14)
        for name in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{name}")(26)
        content.set_hexpand(True)
        content_scroll = Gtk.ScrolledWindow(hexpand=True)
        content_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content_scroll.set_child(content)
        body.append(content_scroll)
        content.append(label("Sua tela, do seu jeito.", "heading"))
        content.append(label("Acompanhe seu Linux em um espaço só seu.", "muted"))
        self.preview_title = label("PRÉVIA AO VIVO  ·  480 × 320", "muted")
        self.preview_title.set_margin_top(10)
        content.append(self.preview_title)
        center = box(False, 0)
        center.set_vexpand(True)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        shell = box(spacing=0)
        shell.add_css_class("preview-shell")
        center.append(shell)
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_size_request(480, 320)
        shell.append(self.picture)
        content.append(center)
        note = label("Prévia com dados reais deste computador.\nUse “Aplicar e iniciar” para enviar à tela USB.", "muted")
        note.set_justify(Gtk.Justification.CENTER)
        note.set_halign(Gtk.Align.CENTER)
        content.append(note)
        status_box = box(spacing=6)
        status_box.add_css_class("status")
        self.device_label = label("Procurando sua tela…", "section")
        self.status_label = label("Painel parado", "muted")
        self.status_label.set_wrap(True)
        self.status_label.set_max_width_chars(60)
        status_box.append(self.device_label)
        status_box.append(self.status_label)
        content.append(status_box)
        secondary = box(False, 10)
        for text, callback in (("Testar cores", self.test_colors), ("Diagnóstico", self.diagnostics), ("Salvar prévia", self.export_preview)):
            button = Gtk.Button(label=text)
            button.connect("clicked", callback)
            secondary.append(button)
        content.append(secondary)
        actions = box(False, 12)
        actions.add_css_class("actions")
        self.feedback = label(initial_error or "Pronto para configurar. Fechar a janela mantém o painel em execução.", "feedback")
        self.feedback.set_wrap(True)
        self.feedback.set_hexpand(True)
        self.feedback.set_max_width_chars(72)
        actions.append(self.feedback)
        stop_button = Gtk.Button(label="Parar painel")
        stop_button.connect("clicked", self.stop)
        actions.append(stop_button)
        apply_button = Gtk.Button(label="Aplicar e iniciar")
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self.apply)
        actions.append(apply_button)
        root.append(actions)
        self.tick()
        self.timer = GLib.timeout_add(1000, self.tick)
        self.connect("close-request", self.on_close)

    def on_close(self, *_):
        GLib.source_remove(self.timer)
        self.sampler.close()
        return False

    def refresh_custom_themes(self):
        previous = getattr(self, "custom_ids", [])
        selected = self.custom.get_selected()
        current = previous[selected] if selected < len(previous) else self.config.custom_theme
        entries = list_themes()
        self.custom_ids = [entry[0] for entry in entries]
        self.custom.set_model(Gtk.StringList.new([entry[1] for entry in entries] or ["Crie um tema no editor"]))
        self.custom.set_selected(self.custom_ids.index(current) if current in self.custom_ids else 0)

    def select_custom_theme(self, theme_id, rotation):
        self.refresh_custom_themes()
        if theme_id in self.custom_ids:
            self.custom.set_selected(self.custom_ids.index(theme_id))
            self.mode.set_selected(list(MODES).index("custom"))
            self.rotation.set_selected(list(ROTATIONS).index(rotation))

    def field(self, parent, title, widget):
        group = box(spacing=5)
        group.append(label(title, "field-label"))
        group.append(widget)
        parent.append(group)

    def dropdown(self, parent, title, choices, current):
        widget = Gtk.DropDown.new_from_strings(list(choices.values()))
        widget.set_selected(list(choices).index(current))
        self.field(parent, title, widget)
        return widget

    def switch_row(self, parent, text, active):
        row = box(False, 10)
        title = label(text, "field-label")
        title.set_hexpand(True)
        row.append(title)
        switch = Gtk.Switch(active=active)
        switch.set_valign(Gtk.Align.CENTER)
        row.append(switch)
        parent.append(row)
        return switch

    def current_config(self):
        mode = list(MODES)[self.mode.get_selected()]
        theme_id = self.custom_ids[self.custom.get_selected()] if self.custom.get_selected() < len(self.custom_ids) else ""
        return Config(port=self.port_entry.get_text().strip() or "auto",
                      brightness=round(self.brightness.get_value()),
                      rotation=list(ROTATIONS)[self.rotation.get_selected()],
                      theme=list(THEMES)[self.theme.get_selected()],
                      mode=mode,
                      title=self.title_entry.get_text(), interval=self.interval.get_value(),
                      image_path=self.image_path, screen_on=self.screen_switch.get_active(),
                      custom_theme=theme_id,
                      custom_theme_data=asdict(load_theme(theme_id)) if mode == "custom" and theme_id else None).validate()

    def tick(self):
        try:
            config = self.current_config()
            if self.sampler.latest is None:
                return True
            self.last_image = render(config, self.sampler.latest)
            data = GLib.Bytes.new(self.last_image.tobytes())
            w, h = self.last_image.size
            texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, data, w * 3)
            self.picture.set_paintable(texture)
            scale = min(1.0, 320 / h)
            self.picture.set_size_request(round(w * scale), round(h * scale))
            self.preview_title.set_text(f"PRÉVIA AO VIVO  ·  {w} × {h}")
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            self.preview_title.set_text(f"PRÉVIA: {exc}")
        if self.poll_count % 3 == 0:
            devices = discover()
            self.device_label.set_text("TURZX 3,5″ encontrada" if devices else "Conecte sua TURZX 3,5″")
        state = service.status()
        self.status_label.set_text(state["message"])
        if state["connected"]:
            self.device_label.add_css_class("connected")
        else:
            self.device_label.remove_css_class("connected")
        self.poll_count += 1
        return True

    def apply(self, *_):
        try:
            config = self.current_config()
            if self.sampler.latest is None:
                raise ValueError("Aguarde a leitura dos sensores.")
            render(config, self.sampler.latest)
            save_config(config)
            set_autostart(self.autostart.get_active())
            self.config = config
            service.start()
            service.request("RELOAD")
            self.feedback.set_text("Configuração salva. Acompanhe a conexão no painel acima.")
            return True
        except (ValueError, OSError, Image.DecompressionBombError) as exc:
            self.feedback.set_text(str(exc))
            return False

    def stop(self, *_):
        if service.request("STOP"):
            self.feedback.set_text("Parando o painel e apagando a tela…")
        else:
            self.feedback.set_text("O painel já está parado.")

    def test_colors(self, *_):
        if not self.screen_switch.get_active():
            self.feedback.set_text("Ative “Tela acesa” para testar as cores.")
            return
        if self.apply():
            attempts = [0]
            def send():
                attempts[0] += 1
                if service.request("TEST"):
                    self.feedback.set_text("Teste solicitado. As cores aparecem por 8 segundos quando há conexão USB.")
                    return False
                if attempts[0] >= 12:
                    self.feedback.set_text("Não foi possível iniciar o painel. Consulte o diagnóstico e o arquivo de log.")
                    return False
                return True
            GLib.timeout_add(250, send)

    def choose_image(self, *_):
        dialog = Gtk.FileChooserNative(title="Escolha uma imagem", transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN, accept_label="Escolher", cancel_label="Cancelar")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Imagens")
        for mime in ("image/png", "image/jpeg", "image/webp", "image/bmp"):
            file_filter.add_mime_type(mime)
        dialog.add_filter(file_filter)
        def response(chooser, code):
            if code == Gtk.ResponseType.ACCEPT:
                try:
                    source = chooser.get_file().get_path()
                    if not source:
                        raise ValueError("Escolha uma imagem armazenada neste computador.")
                    target = config_dir() / "images"
                    target.mkdir(parents=True, exist_ok=True)
                    # Retain previously selected images, so canceling unsaved changes is harmless.
                    import uuid
                    destination = target / f"{uuid.uuid4().hex}.png"
                    with Image.open(source) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                        image.save(destination)
                    self.image_path = str(destination)
                    self.image_label.set_text(Path(source).name)
                    self.mode.set_selected(list(MODES).index("image"))
                    self.tick()
                except (ValueError, OSError, Image.DecompressionBombError) as exc:
                    self.feedback.set_text(f"Não foi possível abrir a imagem: {exc}")
            chooser.destroy()
        dialog.connect("response", response)
        dialog.show()

    def export_preview(self, *_):
        dialog = Gtk.FileChooserNative(title="Salvar prévia", transient_for=self,
                                       action=Gtk.FileChooserAction.SAVE, accept_label="Salvar", cancel_label="Cancelar")
        dialog.set_current_name("turzx-previa.png")
        def response(chooser, code):
            if code == Gtk.ResponseType.ACCEPT and self.last_image:
                try:
                    path = chooser.get_file().get_path()
                    if not path:
                        raise ValueError("Escolha uma pasta local.")
                    self.last_image.save(path, format="PNG")
                    self.feedback.set_text(f"Prévia salva em {path}")
                except (OSError, ValueError) as exc:
                    self.feedback.set_text(str(exc))
            chooser.destroy()
        dialog.connect("response", response)
        dialog.show()

    def diagnostics(self, *_):
        from .diagnostics import diagnose
        dialog = Gtk.Window(title="Diagnóstico · Turzx Linux", transient_for=self, modal=True)
        dialog.set_default_size(650, 440)
        content = box(spacing=12)
        for edge in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{edge}")(20)
        content.append(label("Conexão e suporte USB", "section"))
        text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.get_buffer().set_text(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        scroll = Gtk.ScrolledWindow(vexpand=True, child=text)
        content.append(scroll)
        help_text = label("Se faltar permissão USB: execute instalar.sh e reconecte a tela.\nO log fica em ~/.local/state/turzx-linux/turzx.log", "muted")
        help_text.set_wrap(True)
        content.append(help_text)
        close = Gtk.Button(label="Fechar")
        close.connect("clicked", lambda *_: dialog.close())
        content.append(close)
        dialog.set_child(content)
        dialog.present()


class Application(Gtk.Application):
    def __init__(self, smoke=False):
        super().__init__(application_id="io.github.turzxlinux.Configurator",
                         flags=Gio.ApplicationFlags.NON_UNIQUE if smoke else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.smoke = smoke
        self.window = None
        self.settings_window = None
        self.failure = None
        self.smoke_completed = False

    def open_settings(self):
        if self.settings_window not in self.get_windows():
            self.settings_window = Window(self)
        self.settings_window.present()

    def do_activate(self):
        try:
            self.activate_windows()
        except Exception as exc:
            self.failure = str(exc)
            import traceback
            traceback.print_exc()
            self.quit()

    def activate_windows(self):
        if self.window not in self.get_windows():
            settings = Gtk.Settings.get_default()
            settings.set_property("gtk-application-prefer-dark-theme", True)
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            from .editor import StudioWindow
            self.window = StudioWindow(self)
        self.window.present()
        if self.smoke:
            GLib.timeout_add(2500, self.smoke_done)

    def smoke_done(self):
        try:
            assert self.window.last_image is not None
            assert self.window.picture.get_paintable() is not None
            for container in self.window.model.theme.containers[:2]:
                self.window.select((container.id, None))
                if container.items:
                    self.window.select((container.id, container.items[0].id))
            # Exercise free elements and every new inspector with real GTK widgets.
            from .themes import EditorModel, Theme
            self.window.model = EditorModel(Theme())
            self.window.model.add_text()
            self.window.refresh()
            for category, metric in (("memory", "memory.usage"), ("network", "network.download"), ("gpu", "gpu.usage")):
                self.window.choose_category(category)
                assert self.window.palette.get_first_child() is not None
                for style in ("chart_line", "chart_area", "chart_bars"):
                    self.window.model.add_chart(style, key=metric)
                    self.window.refresh()
                    assert "chart_max" in self.window.inspector_spins
            self.window.grid.set_active(False)
            self.window.paint()
            self.window.select(None)
            self.open_settings()
            self.smoke_completed = True
            print("GTK: editor, textos livres, gráficos, CPU/GPU/RAM/rede, configuração USB e prévia renderizados com sucesso.")
        except Exception as exc:
            self.failure = str(exc) or "A interface não concluiu o teste visual."
        finally:
            self.window.sampler.close()
            if self.settings_window:
                self.settings_window.sampler.close()
            self.quit()
        return False


def main(smoke=False):
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        raise RuntimeError("Não há sessão gráfica. Abra no desktop ou use --run para executar sem interface.")
    app = Application(smoke)
    result = app.run([])
    if app.failure or (smoke and not app.smoke_completed):
        raise RuntimeError(app.failure or "O teste da interface não foi concluído.")
    return result
