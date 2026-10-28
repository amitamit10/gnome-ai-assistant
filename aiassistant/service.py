"""The background service: one process, one D-Bus name, D-Bus-activated on demand, exits when idle.

  /io/github/aiassistant/Search   org.gnome.Shell.SearchProvider2  (GNOME overview search results)
  /io/github/aiassistant/Control  io.github.aiassistant.Control    Open(), Url(), Status(), Quit()  (used by the extension)

It also owns the conversation (session.py) and the microphone (mic.py). The chat window is a separate native GTK process
(native/app.py) that talks to this service over the Control interface, so the extension never spawns anything: it just calls
Open(). Requires PyGObject (python3-gi) from the system.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import config, constants as C  # noqa: E402
from .search import provider, query  # noqa: E402
from .session import Session  # noqa: E402

IDLE_EXIT = 30 * 60

SEARCH_XML = """<node><interface name="org.gnome.Shell.SearchProvider2">
<method name="GetInitialResultSet"><arg type="as" name="terms" direction="in"/><arg type="as" name="results" direction="out"/></method>
<method name="GetSubsearchResultSet"><arg type="as" name="previous_results" direction="in"/><arg type="as" name="terms" direction="in"/><arg type="as" name="results" direction="out"/></method>
<method name="GetResultMetas"><arg type="as" name="identifiers" direction="in"/><arg type="aa{sv}" name="metas" direction="out"/></method>
<method name="ActivateResult"><arg type="s" name="identifier" direction="in"/><arg type="as" name="terms" direction="in"/><arg type="u" name="timestamp" direction="in"/></method>
<method name="LaunchSearch"><arg type="as" name="terms" direction="in"/><arg type="u" name="timestamp" direction="in"/></method>
</interface></node>"""

CONTROL_XML = f"""<node><interface name="{C.CONTROL_IFACE}">
<method name="Open"/>
<method name="Ask"><arg type="s" name="text" direction="in"/><arg type="s" name="error" direction="out"/></method>
<method name="History"><arg type="s" name="json" direction="out"/></method>
<method name="Reset"><arg type="b" name="ok" direction="out"/></method>
<method name="OpenFile"><arg type="s" name="path" direction="in"/><arg type="b" name="ok" direction="out"/></method>
<method name="SttStart"><arg type="s" name="error" direction="out"/></method>
<method name="SttStop"><arg type="s" name="json" direction="out"/></method>
<method name="Status"><arg type="s" name="json" direction="out"/></method>
<method name="Quit"/>
<signal name="Progress"><arg type="s" name="text"/></signal>
<signal name="Reply"><arg type="s" name="json"/></signal>
</interface></node>"""


class Service:
    def __init__(self):
        self.provider = provider.Provider()
        self.session = Session()
        self.conn = None
        self.mic = None
        self.loop = None
        self.last_open = 0.0
        self.last_activity = time.time()

    # ------------------------------------------------------------------ chat window
    def open_window(self):
        """Start the native chat window (or raise it when it is already running: it is a single-instance GTK application)."""
        now = time.time()
        if now - self.last_open < 1.0:  # ignore a double press while the window is still starting
            return
        self.last_open = now
        override = os.environ.get("AIASSISTANT_WINDOW_CMD")  # tests replace the window with a recorder
        argv = shlex.split(override) if override else [sys.executable, "-m", "aiassistant", "window"]
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def _emit(self, signal, text):
        def go():
            if self.conn:
                self.conn.emit_signal(None, C.CONTROL_PATH, C.CONTROL_IFACE, signal, GLib.Variant("(s)", (text,)))
            return False
        GLib.idle_add(go)

    # ------------------------------------------------------------------ D-Bus
    def _search(self, method, args, inv):
        self.last_activity = time.time()
        if method in ("GetInitialResultSet", "GetSubsearchResultSet"):
            terms = list(args[0] if method == "GetInitialResultSet" else args[1])

            def work():
                try:
                    res = self.provider.results(terms)
                except Exception as e:  # never let a bad query kill the service
                    print("search failed:", e, file=sys.stderr, flush=True)
                    res = []
                GLib.idle_add(lambda: bool(inv.return_value(GLib.Variant("(as)", (res,)))) and False)

            threading.Thread(target=work, daemon=True).start()
        elif method == "GetResultMetas":
            metas = [{k: GLib.Variant("s", v) for k, v in provider.meta_for(i).items()} for i in args[0]]
            inv.return_value(GLib.Variant("(aa{sv})", (metas,)))
        elif method == "ActivateResult":
            self.provider.activate(args[0])
            inv.return_value(None)
        else:  # LaunchSearch: nothing beyond the overview list
            inv.return_value(None)

    def _control(self, method, args, inv):
        self.last_activity = time.time()
        ret = lambda fmt, *v: inv.return_value(GLib.Variant(fmt, v))
        if method == "Open":
            self.open_window()
            inv.return_value(None)
        elif method == "Ask":
            err = self.session.ask(args[0], lambda s: self._emit("Progress", s), lambda r: self._emit("Reply", json.dumps(r)))
            ret("(s)", err or "")
        elif method == "History":
            ret("(s)", json.dumps(self.session.snapshot()))
        elif method == "Reset":
            ret("(b)", self.session.reset())
        elif method == "OpenFile":
            from .tools import files
            ret("(b)", files.open_file(args[0]))
        elif method == "SttStart":
            def start():
                from .mic import Mic
                err = ""
                try:
                    if self.mic:
                        self.mic.cancel()
                    self.mic = Mic()
                    self.mic.start()
                except Exception as e:
                    self.mic, err = None, str(e)[:200]
                GLib.idle_add(lambda: bool(ret("(s)", err)) and False)
            threading.Thread(target=start, daemon=True).start()
        elif method == "SttStop":
            def stop():
                mic, self.mic = self.mic, None
                try:
                    out = {"text": mic.stop()} if mic else {"text": ""}
                    if mic and not out["text"] and mic.error():
                        out = {"error": mic.error()}
                except Exception as e:
                    out = {"error": str(e)[:200]}
                GLib.idle_add(lambda: bool(ret("(s)", json.dumps(out))) and False)
            threading.Thread(target=stop, daemon=True).start()
        elif method == "Status":
            ret("(s)", json.dumps({"pid": os.getpid(), "busy": self.session.busy}))
        elif method == "Quit":
            inv.return_value(None)
            GLib.idle_add(self.loop.quit)

    def _tick(self):
        query.shared().unload_if_idle()
        self.session.chat.maintenance()
        if self.mic and time.time() - self.mic.live.started > 200:  # the window died while recording: stop listening
            mic, self.mic = self.mic, None
            mic.cancel()
        if time.time() - self.last_activity > IDLE_EXIT and not self.session.busy:
            self.loop.quit()
        return True

    def run(self):
        search_node, control_node = Gio.DBusNodeInfo.new_for_xml(SEARCH_XML), Gio.DBusNodeInfo.new_for_xml(CONTROL_XML)

        def on_bus(conn, name):
            self.conn = conn
            conn.register_object(C.SEARCH_PATH, search_node.interfaces[0],
                                 lambda c, s, p, i, m, params, inv: self._search(m, params.unpack(), inv), None, None)
            conn.register_object(C.CONTROL_PATH, control_node.interfaces[0],
                                 lambda c, s, p, i, m, params, inv: self._control(m, params.unpack(), inv), None, None)

        def on_lost(conn, name):
            print("could not own", name, "(is another instance running?)", file=sys.stderr)
            self.loop.quit()

        Gio.bus_own_name(Gio.BusType.SESSION, C.BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_bus, None, on_lost)
        GLib.timeout_add_seconds(60, self._tick)
        self.loop = GLib.MainLoop()
        self.loop.run()


def main():
    Service().run()


if __name__ == "__main__":
    main()
