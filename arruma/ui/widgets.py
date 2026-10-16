"""Componentes reutilizáveis da interface."""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from ..core import taxonomy as tx  # noqa: E402
from ..core.system import IS_MAC, IS_WINDOWS, NO_WINDOW  # noqa: E402

CSS_PATH = Path(__file__).with_name("style.css")

# Alternativas para ícones que nem todos os temas têm (no Windows e no macOS o Arruma leva o
# tema Adwaita, que só tem parte dos ícones coloridos do Linux Mint).
_ICON_FALLBACKS = {
    "folder-download": ["folder-download-symbolic", "folder"],
    "user-desktop": ["user-desktop-symbolic", "user-home-symbolic", "folder"],
    "folder-documents": ["folder-documents-symbolic", "folder"],
    "folder-pictures": ["folder-pictures-symbolic", "folder"],
    "folder-videos": ["folder-videos-symbolic", "folder"],
    "folder-music": ["folder-music-symbolic", "folder"],
    "user-home": ["user-home-symbolic", "go-home-symbolic", "folder"],
    "folder-open": ["folder-open-symbolic", "folder"],
    "folder-new": ["folder-new-symbolic", "folder"],
    "computer": ["computer-symbolic", "drive-harddisk"],
    "computer-symbolic": ["computer", "drive-harddisk-symbolic"],
    "x-office-document": ["x-office-document-symbolic", "text-x-generic", "text-x-generic-symbolic"],
    "image-x-generic": ["image-x-generic-symbolic", "text-x-generic"],
    "video-x-generic": ["video-x-generic-symbolic", "text-x-generic"],
    "audio-x-generic": ["audio-x-generic-symbolic", "text-x-generic"],
    "package-x-generic": ["package-x-generic-symbolic", "text-x-generic"],
    "application-x-executable": ["application-x-executable-symbolic", "system-run-symbolic", "text-x-generic"],
    "text-x-script": ["text-x-script-symbolic", "text-x-generic"],
    "text-x-generic": ["text-x-generic-symbolic"],
    "user-trash": ["user-trash-symbolic", "user-trash-full"],
    "applications-science-symbolic": ["applications-science", "system-run-symbolic", "emblem-system-symbolic"],
    "network-offline-symbolic": ["network-wired-disconnected-symbolic", "network-offline"],
    "view-dual-symbolic": ["view-paged-symbolic", "view-list-symbolic"],
    "view-paged-symbolic": ["view-list-symbolic"],
    "view-grid-symbolic": ["view-app-grid-symbolic", "view-list-symbolic"],
    "security-high-symbolic": ["security-medium-symbolic", "channel-secure-symbolic", "emblem-ok-symbolic"],
    "applications-system-symbolic": ["preferences-system-symbolic"],
    "emblem-ok-symbolic": ["object-select-symbolic", "emblem-default-symbolic", "checkbox-checked-symbolic"],
    "web-browser-symbolic": ["applications-internet-symbolic", "network-workgroup-symbolic"],
}
_RESOLVED: dict[str, str] = {}
MISSING_ICONS: set[str] = set()


def resolve_icon(name: str) -> str:
    """Nome de ícone que existe no tema atual (com alternativas se o original faltar)."""
    if name in _RESOLVED:
        return _RESOLVED[name]
    theme = Gtk.IconTheme.get_default()
    found = name
    if theme is not None and not theme.has_icon(name):
        alt = name[:-9] if name.endswith("-symbolic") else name + "-symbolic"
        for cand in [alt] + _ICON_FALLBACKS.get(name, []):
            if theme.has_icon(cand):
                found = cand
                break
        else:
            MISSING_ICONS.add(name)
    _RESOLVED[name] = found
    return found


def load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(CSS_PATH))
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def esc(text: str) -> str:
    return GLib.markup_escape_text(text or "")


def add_classes(widget: Gtk.Widget, *classes: str) -> Gtk.Widget:
    ctx = widget.get_style_context()
    for c in classes:
        if c:
            ctx.add_class(c)
    return widget


def label(text: str = "", *classes: str, xalign: float = 0.0, wrap: bool = False,
          markup: bool = False, selectable: bool = False, ellipsize: bool = False,
          max_width: int = -1, justify: Gtk.Justification | None = None, **props) -> Gtk.Label:
    lbl = Gtk.Label(**props)
    if markup:
        lbl.set_markup(text)
    else:
        lbl.set_text(text)
    lbl.set_xalign(xalign)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    if max_width > 0:
        lbl.set_max_width_chars(max_width)
    if justify is not None:
        lbl.set_justify(justify)
    lbl.set_selectable(selectable)
    add_classes(lbl, *classes)
    return lbl


def icon(name: str, size: int = 16, *classes: str) -> Gtk.Image:
    img = Gtk.Image.new_from_icon_name(resolve_icon(name), Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    add_classes(img, *classes)
    return img


def button(text: str = "", icon_name: str | None = None, *classes: str,
           on_click: Callable | None = None, tooltip: str | None = None) -> Gtk.Button:
    btn = Gtk.Button()
    if icon_name and text:
        box = Gtk.Box(spacing=6)
        box.pack_start(icon(icon_name, 16), False, False, 0)
        box.pack_start(Gtk.Label(label=text), False, False, 0)
        box.set_halign(Gtk.Align.CENTER)
        btn.add(box)
    elif icon_name:
        btn.add(icon(icon_name, 16))
    else:
        btn.set_label(text)
    add_classes(btn, *classes)
    if on_click:
        btn.connect("clicked", lambda *_: on_click())
    if tooltip:
        btn.set_tooltip_text(tooltip)
    return btn


def vbox(spacing: int = 0, *classes: str, **kw) -> Gtk.Box:
    return add_classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, **kw), *classes)


def hbox(spacing: int = 0, *classes: str, **kw) -> Gtk.Box:
    return add_classes(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, **kw), *classes)


def card(*classes: str, spacing: int = 10, horizontal: bool = False) -> Gtk.Box:
    box = hbox(spacing) if horizontal else vbox(spacing)
    return add_classes(box, "card", *classes)


def kind_icon(kind: str) -> str:
    return resolve_icon(tx.KIND_INFO.get(kind, tx.KIND_INFO[tx.OTHER])[2])


def kind_label(kind: str) -> str:
    return tx.KIND_INFO.get(kind, tx.KIND_INFO[tx.OTHER])[0]


def kind_color(kind: str) -> str:
    return tx.KIND_INFO.get(kind, tx.KIND_INFO[tx.OTHER])[1]


def hex_rgba(color: str) -> tuple[float, float, float, float]:
    rgba = Gdk.RGBA()
    rgba.parse(color)
    return rgba.red, rgba.green, rgba.blue, rgba.alpha


# --------------------------------------------------------------------------- abrir ficheiros

def open_path(path: str) -> None:
    """Abre o ficheiro ou a pasta com o programa predefinido do sistema."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except (GLib.Error, OSError):
        pass


def open_url(url: str) -> None:
    """Abre um endereço da internet no navegador predefinido."""
    try:
        if IS_WINDOWS:
            os.startfile(url)  # noqa: S606
        elif IS_MAC:
            subprocess.Popen(["open", url])
        else:
            Gio.AppInfo.launch_default_for_uri(url, None)
    except (GLib.Error, OSError):
        pass


def show_in_folder(path: str) -> None:
    """Abre o gestor de ficheiros (Nemo, Explorador, Finder) com o ficheiro selecionado."""
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"], creationflags=NO_WINDOW)
            return
        if IS_MAC:
            subprocess.Popen(["open", "-R", path])
            return
    except OSError:
        pass
    else:
        uri = Gio.File.new_for_path(path).get_uri()
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                          "org.freedesktop.FileManager1", "ShowItems",
                          GLib.Variant("(ass)", ([uri], "")), None, Gio.DBusCallFlags.NONE, 2000, None)
            return
        except GLib.Error:
            pass
    parent = path if os.path.isdir(path) else os.path.dirname(path)
    open_path(parent)


# --------------------------------------------------------------------------- tarefas em segundo plano

def run_bg(fn: Callable, on_done: Callable, on_error: Callable | None = None) -> threading.Thread:
    def worker():
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 — mostrado ao utilizador
            traceback.print_exc()
            if on_error:
                # «e» deixa de existir no fim do except: passa-se o erro como argumento.
                GLib.idle_add(lambda err: (on_error(err), False)[1], e)
            return
        GLib.idle_add(lambda: (on_done(result), False)[1])
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


class Throttle:
    """Envia atualizações de progresso para a interface no máximo 10 vezes por segundo."""

    def __init__(self, fn: Callable, interval: float = 0.1):
        self.fn = fn
        self.interval = interval
        self.last = 0.0

    def __call__(self, *args, force: bool = False):
        now = time.monotonic()
        if force or now - self.last >= self.interval:
            self.last = now
            GLib.idle_add(lambda: (self.fn(*args), False)[1])


# --------------------------------------------------------------------------- componentes

class StatCard(Gtk.Box):
    def __init__(self, icon_name: str, value: str, caption: str):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        add_classes(self, "card")
        img = icon(icon_name, 22, "insight-icon")
        img.set_valign(Gtk.Align.CENTER)
        self.pack_start(img, False, False, 0)
        col = vbox(0)
        self.value = label(value, "stat-value")
        self.caption = label(caption, "stat-label")
        col.pack_start(self.value, False, False, 0)
        col.pack_start(self.caption, False, False, 0)
        self.pack_start(col, True, True, 0)

    def set(self, value: str, caption: str | None = None) -> None:
        self.value.set_text(value)
        if caption is not None:
            self.caption.set_text(caption)


class DonutChart(Gtk.DrawingArea):
    def __init__(self, size: int = 200):
        super().__init__()
        self.set_size_request(size, size)
        self.data: list[tuple[str, float, str]] = []
        self.center_title = ""
        self.center_sub = ""

    def set_data(self, data: list[tuple[str, float, str]], title: str, sub: str) -> None:
        self.data = [d for d in data if d[1] > 0]
        self.center_title, self.center_sub = title, sub
        self.queue_draw()

    def do_draw(self, cr) -> bool:
        w, h = self.get_allocated_width(), self.get_allocated_height()
        size = min(w, h)
        cx, cy = w / 2, h / 2
        lw = size * 0.13
        r = size / 2 - lw / 2 - 2
        fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        total = sum(v for _, v, _ in self.data)
        cr.set_line_width(lw)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if total > 0:
            start = -math.pi / 2
            gap = 0.025 if len(self.data) > 1 else 0
            for _, value, color in self.data:
                sweep = value / total * 2 * math.pi
                if sweep > gap * 2:
                    cr.set_source_rgba(*hex_rgba(color))
                    cr.arc(cx, cy, r, start + gap, start + sweep - gap)
                    cr.stroke()
                start += sweep
        for text, scale, alpha, dy in ((self.center_title, 1.5, 1.0, -0.55), (self.center_sub, 0.85, 0.6, 0.75)):
            layout = self.create_pango_layout(text)
            desc = self.get_pango_context().get_font_description().copy()
            desc.set_size(int(desc.get_size() * scale))
            if scale > 1:
                desc.set_weight(Pango.Weight.HEAVY)
            layout.set_font_description(desc)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
            cr.move_to(cx - tw / 2, cy - th / 2 + dy * th)
            PangoCairo.show_layout(cr, layout)
        return False


class ProgressPanel(Gtk.Box):
    """Ecrã de espera com spinner, barra de progresso e botão de cancelar."""

    def __init__(self, on_cancel: Callable | None = None, secondary: tuple[str, Callable] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_size_request(460, -1)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(42, 42)
        self.title = label("", "page-title", xalign=0.5)
        self.detail = label("", "dim", xalign=0.5, ellipsize=True, max_width=60)
        self.bar = Gtk.ProgressBar()
        self.bar.set_show_text(False)
        self.counter = label("", "small", "dim", xalign=0.5)
        self.hint = label("", "small", "dim", xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
        for w in (self.spinner, self.title, self.detail, self.bar, self.counter, self.hint):
            self.pack_start(w, False, False, 0)
        btns = hbox(10, halign=Gtk.Align.CENTER, margin_top=8)
        self.secondary_btn = None
        if secondary:
            self.secondary_btn = button(secondary[0], None, on_click=secondary[1])
            btns.pack_start(self.secondary_btn, False, False, 0)
        if on_cancel:
            btns.pack_start(button("Cancelar", None, on_click=on_cancel), False, False, 0)
        self.pack_start(btns, False, False, 0)

    def start(self, title: str, hint: str = "") -> None:
        self.title.set_text(title)
        self.detail.set_text("")
        self.counter.set_text("")
        self.hint.set_text(hint)
        self.hint.set_visible(bool(hint))
        self.bar.set_fraction(0)
        self.spinner.start()
        if self.secondary_btn:
            self.secondary_btn.set_visible(False)

    def update(self, detail: str = "", fraction: float | None = None, counter: str = "",
               title: str | None = None) -> None:
        if title:
            self.title.set_text(title)
        self.detail.set_text(detail)
        self.counter.set_text(counter)
        if fraction is None:
            self.bar.pulse()
        else:
            self.bar.set_fraction(max(0.0, min(1.0, fraction)))

    def stop(self) -> None:
        self.spinner.stop()


class Placeholder(Gtk.Box):
    def __init__(self, icon_name: str, title: str, text: str,
                 action: tuple[str, Callable] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        img = icon(icon_name, 72)
        img.set_opacity(0.35)
        self.pack_start(img, False, False, 0)
        self.title = label(title, "page-title", xalign=0.5)
        self.text = label(text, "dim", xalign=0.5, wrap=True, max_width=56, justify=Gtk.Justification.CENTER)
        self.pack_start(self.title, False, False, 0)
        self.pack_start(self.text, False, False, 0)
        if action:
            btn = button(action[0], None, "suggested-action", "big-button", on_click=action[1])
            btn.set_halign(Gtk.Align.CENTER)
            btn.set_margin_top(10)
            self.pack_start(btn, False, False, 0)


class Toast(Gtk.Revealer):
    def __init__(self):
        super().__init__()
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(70)
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        box = hbox(10, "toast")
        self.text = label("")
        self.action_btn = Gtk.Button()
        self.action_btn.connect("clicked", self._on_action)
        close = Gtk.Button()
        close.add(icon("window-close-symbolic", 14))
        add_classes(close, "close")
        close.connect("clicked", lambda *_: self.set_reveal_child(False))
        box.pack_start(self.text, False, False, 0)
        box.pack_start(self.action_btn, False, False, 0)
        box.pack_start(close, False, False, 0)
        self.add(box)
        self._callback = None
        self._timeout = 0

    def show(self, text: str, action: str | None = None, callback: Callable | None = None,
             seconds: int = 7) -> None:
        self.text.set_text(text)
        self._callback = callback
        self.action_btn.set_visible(bool(action))
        if action:
            self.action_btn.set_label(action)
        self.set_reveal_child(True)
        if self._timeout:
            GLib.source_remove(self._timeout)
        self._timeout = GLib.timeout_add_seconds(seconds, self._hide)

    def _hide(self):
        self._timeout = 0
        self.set_reveal_child(False)
        return False

    def _on_action(self, *_):
        self.set_reveal_child(False)
        if self._callback:
            self._callback()


def pref_row(title: str, subtitle: str, widget: Gtk.Widget | None) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    row.set_selectable(False)
    box = hbox(16)
    col = vbox(2)
    col.pack_start(label(title), False, False, 0)
    if subtitle:
        col.pack_start(label(subtitle, "small", "dim", wrap=True, max_width=70), False, False, 0)
    box.pack_start(col, True, True, 0)
    if widget is not None:
        widget.set_valign(Gtk.Align.CENTER)
        box.pack_end(widget, False, False, 0)
    row.add(box)
    return row


def pref_group(rows: list[Gtk.ListBoxRow]) -> Gtk.ListBox:
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    add_classes(lb, "pref-group")
    for r in rows:
        lb.add(r)
    return lb


def message(parent: Gtk.Window, title: str, text: str, kind=Gtk.MessageType.INFO) -> None:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                            buttons=Gtk.ButtonsType.OK, text=title)
    dlg.format_secondary_text(text)
    dlg.run()
    dlg.destroy()


def confirm(parent: Gtk.Window, title: str, text: str, ok_label: str,
            destructive: bool = False) -> bool:
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=title)
    dlg.format_secondary_text(text)
    dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(ok_label, Gtk.ResponseType.OK)
    add_classes(ok, "destructive-action" if destructive else "suggested-action")
    dlg.set_default_response(Gtk.ResponseType.OK)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK


def choose_folder(parent: Gtk.Window, title: str, start: str | None = None) -> str | None:
    dlg = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, "Escolher", "Cancelar")
    if start and os.path.isdir(start):
        dlg.set_current_folder(start)
    resp = dlg.run()
    path = dlg.get_filename() if resp == Gtk.ResponseType.ACCEPT else None
    dlg.destroy()
    return path


def choose_folders(parent: Gtk.Window, title: str, start: str | None = None) -> list[str]:
    dlg = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, "Escolher", "Cancelar")
    dlg.set_select_multiple(True)
    if start and os.path.isdir(start):
        dlg.set_current_folder(start)
    resp = dlg.run()
    paths = list(dlg.get_filenames() or []) if resp == Gtk.ResponseType.ACCEPT else []
    dlg.destroy()
    return [p for p in paths if p and os.path.isdir(p)]


def prompt_text(parent: Gtk.Window, title: str, subtitle: str, initial: str = "",
                ok_label: str = "Guardar") -> str | None:
    dlg = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    ok = dlg.add_button(ok_label, Gtk.ResponseType.OK)
    add_classes(ok, "suggested-action")
    dlg.set_default_response(Gtk.ResponseType.OK)
    dlg.set_default_size(420, -1)
    box = dlg.get_content_area()
    inner = vbox(8, margin_top=14, margin_bottom=14, margin_start=18, margin_end=18)
    if subtitle:
        inner.pack_start(label(subtitle, "small", "dim", wrap=True, max_width=52), False, False, 0)
    entry = Gtk.Entry(text=initial, activates_default=True)
    inner.pack_start(entry, False, False, 0)
    box.add(inner)
    dlg.show_all()
    entry.grab_focus()
    resp = dlg.run()
    val = entry.get_text().strip() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    return val or None


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "a calcular o tempo restante…"
    if seconds < 60:
        return "menos de 1 minuto"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"cerca de {minutes} min"
    return f"cerca de {minutes // 60} h {minutes % 60:02d} min"
