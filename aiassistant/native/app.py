"""The native chat window (GTK 4 + libadwaita). A thin client: the conversation, tools and microphone live in the service."""
import json
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import constants as C, paths  # noqa: E402
from . import style, widgets  # noqa: E402
from .markup import to_pango  # noqa: E402

APP_ID = "io.github.aiassistant.Chat"
TITLE = "AI Assistant"  # the Shell extension finds the window by this exact title
SUGGESTIONS = [("weather-clear-symbolic", "What's the weather today?"), ("battery-symbolic", "How is my battery?"),
               ("system-search-symbolic", "Find my notes about Vercel"), ("network-wireless-symbolic", "Which Wi-Fi am I on?")]


class Service:
    """Async calls to the background service over D-Bus (it is started on demand by the first call)."""

    def __init__(self, on_progress, on_reply, on_owner):
        self.proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, C.BUS_NAME,
                                                    C.CONTROL_PATH, C.CONTROL_IFACE, None)
        self.on_progress, self.on_reply = on_progress, on_reply
        self.proxy.connect("g-signal", self._signal)
        self.proxy.connect("notify::g-name-owner", lambda *_: on_owner())

    def _signal(self, _p, _sender, name, params):
        if name == "Progress":
            self.on_progress(params.unpack()[0])
        elif name == "Reply":
            self.on_reply(json.loads(params.unpack()[0]))

    def call(self, method, args=None, then=None, timeout=60000):
        """then(result_tuple_or_None, error_message_or_None) runs on the main loop."""
        params = GLib.Variant(f"({args[0]})", (args[1],)) if args else None

        def done(proxy, res):
            try:
                out = proxy.call_finish(res).unpack()
                err = None
            except GLib.Error as e:
                out, err = None, e.message
            if then:
                then(out, err)
        self.proxy.call(method, params, Gio.DBusCallFlags.NONE, timeout, None, done)


class Ctx:
    """What widgets may do: send a message, open a link or file, copy text."""

    def __init__(self, win):
        self.win = win

    def send(self, text):
        self.win.submit(text)

    def open_url(self, url):
        if url.startswith(("http://", "https://")):
            Gtk.UriLauncher.new(url).launch(self.win, None, None, None)

    def open_file(self, path):
        self.win.service.call("OpenFile", ("s", path))

    def copy(self, text):
        self.win.get_clipboard().set(text)


class ChatWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=TITLE, default_width=720, default_height=680)
        self.ctx = Ctx(self)
        self.busy = False
        self.recording = False
        self.thinking = None
        self.service = Service(self._on_progress, self._on_reply, self._load_history)

        view = Adw.ToolbarView()
        self.title_widget = Adw.WindowTitle(title="Assistant", subtitle="")
        header = Adw.HeaderBar(title_widget=self.title_widget)
        new = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="New chat")
        new.connect("clicked", lambda _b: self.new_chat())
        header.pack_start(new)
        view.add_top_bar(header)

        self.log = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=560, child=self.log)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=clamp)
        self.empty = self._empty_page()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(self.scroller, "chat")
        view.set_content(self.stack)

        self.entry = Gtk.Entry(placeholder_text="Ask anything: weather, news, your files…", hexpand=True)
        self.entry.connect("activate", lambda _e: self.submit())
        self.mic = Gtk.Button(icon_name="audio-input-microphone-symbolic", tooltip_text="Voice input")
        self.mic.add_css_class("circular")
        self.mic.connect("clicked", lambda _b: self.toggle_mic())
        self.send_btn = Gtk.Button(icon_name="paper-plane-symbolic" if Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon("paper-plane-symbolic") else "go-up-symbolic")
        self.send_btn.add_css_class("circular")
        self.send_btn.add_css_class("suggested-action")
        self.send_btn.connect("clicked", lambda _b: self.submit())
        bar = Gtk.Box(spacing=8, margin_top=8, margin_bottom=10, margin_start=12, margin_end=12)
        for w in (self.entry, self.mic, self.send_btn):
            bar.append(w)
        view.add_bottom_bar(Adw.Clamp(maximum_size=720, child=bar))
        self.set_content(view)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"), Gtk.CallbackAction.new(lambda *_: self.close() or True)))
        self.add_controller(esc)
        self._load_history()
        self.entry.grab_focus()

    # ------------------------------------------------------------------ pages
    def _empty_page(self):
        page = Adw.StatusPage(icon_name="chat-bubble-text-symbolic", title="How can I help?",
                              description="Ask about the weather, the news, your files or this computer.")
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, max_children_per_line=2, halign=Gtk.Align.CENTER,
                            column_spacing=8, row_spacing=8)
        for icon, text in SUGGESTIONS:
            b = Gtk.Button(child=Gtk.Box(spacing=8))
            b.get_child().append(Gtk.Image.new_from_icon_name(icon))
            b.get_child().append(Gtk.Label(label=text))
            b.add_css_class("pill")
            b.connect("clicked", lambda _b, t=text: self.submit(t))
            chips.append(b)
        page.set_child(chips)
        return page

    def _load_history(self):
        def got(out, err):
            if err or not out:
                return
            snap = json.loads(out[0])
            self._clear()
            for it in snap["items"]:
                if it["role"] == "user":
                    self._add_user(it["text"])
                else:
                    self._add_reply(it, history=True)
            self.title_widget.set_subtitle(snap.get("model") or "")
            if snap.get("busy"):
                self._set_busy(True, snap.get("status") or "Thinking")
            self._refresh_stack()
        self.service.call("History", None, got)

    def _clear(self):
        child = self.log.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.log.remove(child)
            child = nxt
        self.thinking = None

    def _refresh_stack(self):
        self.stack.set_visible_child_name("chat" if self.log.get_first_child() else "empty")

    # ------------------------------------------------------------------ rendering
    def _add_user(self, text):
        bubble = Gtk.Label(label=text, wrap=True, selectable=True, xalign=0, max_width_chars=48, natural_wrap_mode=Gtk.NaturalWrapMode.WORD)
        bubble.add_css_class("sf-user")
        bubble.set_halign(Gtk.Align.END)
        self.log.append(bubble)
        self._scroll_soon()

    def _text_label(self, text):
        lb = Gtk.Label(wrap=True, selectable=True, xalign=0, use_markup=True, natural_wrap_mode=Gtk.NaturalWrapMode.WORD)
        lb.set_label(to_pango(text))
        lb.add_css_class("sf-bot")
        lb.connect("activate-link", lambda _l, uri: (self.ctx.open_url(uri), True)[1])
        return lb

    def _add_reply(self, r, history=False):
        if r.get("error"):
            note = Gtk.Label(label=r["error"], wrap=True, selectable=True, xalign=0)
            note.add_css_class("sf-error-note")
            self.log.append(note)
        else:
            rows = {}
            for w in r.get("widgets", []):
                rows.setdefault(w.get("row", 0), []).append(w)
            if r.get("text"):
                self.log.append(self._text_label(r["text"]))
            for _row, items in sorted(rows.items()):
                built = [widgets.build(w["widget"], w["data"], self.ctx) for w in items]
                if len(built) == 1:
                    self.log.append(built[0])
                else:
                    line = Gtk.Box(spacing=10, homogeneous=True)
                    for b in built:
                        b.set_hexpand(True)
                        line.append(b)
                    self.log.append(line)
            if r.get("followups") and not history:
                chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, max_children_per_line=3,
                                    column_spacing=6, row_spacing=6)
                for f in r["followups"]:
                    b = Gtk.Button(label=f)
                    b.add_css_class("pill")
                    b.connect("clicked", lambda _b, t=f: self.submit(t))
                    chips.append(b)
                self.log.append(chips)
            if r.get("model") and not history:
                self.title_widget.set_subtitle(r["model"])
        self._scroll_soon()

    def _scroll_soon(self):
        adj = self.scroller.get_vadjustment()
        for ms in (30, 250, 700):  # charts and images settle after the first layout
            GLib.timeout_add(ms, lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) or False)

    # ------------------------------------------------------------------ conversation
    def _set_busy(self, busy, status="Thinking"):
        self.busy = busy
        for w in (self.entry, self.send_btn):
            w.set_sensitive(not busy)
        if busy and not self.thinking:
            self.spinner = Gtk.Spinner(spinning=True)
            self.status_label = Gtk.Label(label=status, xalign=0)
            self.status_label.add_css_class("dim-label")
            self.thinking = Gtk.Box(spacing=10)
            self.thinking.append(self.spinner)
            self.thinking.append(self.status_label)
            self.log.append(self.thinking)
            self._scroll_soon()
        elif busy:
            self.status_label.set_label(status)
        elif self.thinking:
            self.log.remove(self.thinking)
            self.thinking = None
            self.entry.grab_focus()

    def submit(self, text=None):
        text = (text if text is not None else self.entry.get_text()).strip()
        if not text or self.busy:
            return
        self.entry.set_text("")
        self._add_user(text)
        self._set_busy(True)
        self._refresh_stack()

        def sent(out, err):
            problem = err or (out[0] if out else "")
            if problem:
                self._set_busy(False)
                self._add_reply({"error": problem})
        self.service.call("Ask", ("s", text), sent)

    def _on_progress(self, text):
        if self.thinking and text:
            self.status_label.set_label(text)

    def _on_reply(self, r):
        self._set_busy(False)
        self._add_reply(r)

    def new_chat(self):
        if self.busy:
            return
        self.service.call("Reset", None, lambda *_: (self._clear(), self.title_widget.set_subtitle(""), self._refresh_stack()))

    # ------------------------------------------------------------------ microphone
    def toggle_mic(self):
        if not self.recording:
            def started(out, err):
                problem = err or (out[0] if out else "")
                if problem:
                    self._add_reply({"error": f"Voice input unavailable: {problem}"})
                    self._refresh_stack()
                    return
                self.recording = True
                self.mic.add_css_class("sf-recording")
                self.entry.set_placeholder_text("Listening… click the microphone again to finish")
            self.service.call("SttStart", None, started)
        else:
            self.recording = False
            self.mic.remove_css_class("sf-recording")
            self.mic.set_sensitive(False)
            self.entry.set_placeholder_text("Transcribing…")

            def stopped(out, err):
                self.mic.set_sensitive(True)
                self.entry.set_placeholder_text("Ask anything: weather, news, your files…")
                res = json.loads(out[0]) if out else {"error": err}
                if res.get("error"):
                    self._add_reply({"error": f"Voice input failed: {res['error']}"})
                elif res.get("text"):
                    self.entry.set_text(res["text"])
                    self.entry.set_position(-1)
                self.entry.grab_focus()
                self._refresh_stack()
            self.service.call("SttStop", None, stopped, 30000)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.load()

    def do_activate(self):
        if not self.win:
            self.win = ChatWindow(self)
            self.win.connect("close-request", self._closed)
        self.win.present()

    def _closed(self, _w):
        self.win = None
        return False


def main():
    return App().run(sys.argv[:1])
