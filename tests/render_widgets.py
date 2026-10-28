"""Render every widget with its example data to PNGs (for looking at, and used by test_native.py).

    python tests/render_widgets.py OUTDIR            # needs a display: run under xvfb-run, or in a desktop session
"""
import json
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from aiassistant import paths  # noqa: E402
from aiassistant.native import style, widgets as nw  # noqa: E402
from aiassistant.ui import widgets as uw  # noqa: E402


class FakeCtx:
    def send(self, t): pass
    def open_url(self, u): pass
    def open_file(self, p): pass
    def copy(self, t): pass


def shoot(widget, path, width=680):
    win = Adw.Window(default_width=width, default_height=10)
    holder = Gtk.Box(margin_top=10, margin_bottom=10, margin_start=10, margin_end=10, valign=Gtk.Align.START)
    widget.set_hexpand(True)
    holder.add_css_class('background')  # a window-coloured backdrop, as in the real window
    holder.append(widget)
    win.set_content(holder)
    done = {}

    def grab():
        paint = Gtk.WidgetPaintable.new(holder)
        w, h = holder.get_width(), holder.get_height()
        snap = Gtk.Snapshot()
        paint.snapshot(snap, w, h)
        node = snap.to_node()
        tex = win.get_native().get_renderer().render_texture(node, None)
        tex.save_to_png(path)
        done["size"] = (w, h)
        win.destroy()
        loop.quit()
        return False
    win.present()
    GLib.timeout_add(900, grab)
    loop = GLib.MainLoop()
    loop.run()
    return done.get("size")


def main(out):
    Adw.init()
    style.load()
    sizes = {}
    for n in uw.names():
        sizes[n] = shoot(nw.build(n, uw.load(n)["example"], FakeCtx()), f"{out}/{n}.png")
    print(json.dumps(sizes))


if __name__ == "__main__":
    main(sys.argv[1])
