"""Load the window stylesheet. Tinted backgrounds are computed from the theme's own colours at startup (a CSS alpha() on a
named colour was not reliable across themes), so they follow the active GTK theme and accent."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .. import paths  # noqa: E402

FALLBACK = {"accent_bg_color": (53, 132, 228), "success_color": (143, 240, 164), "warning_color": (248, 228, 92),
            "error_color": (255, 123, 99), "window_fg_color": (255, 255, 255)}


def _rgba(probe, name, alpha):
    ok, c = probe.get_style_context().lookup_color(name)
    r, g, b = (round(c.red * 255), round(c.green * 255), round(c.blue * 255)) if ok else FALLBACK[name]
    return f"rgba({r},{g},{b},{alpha})"


def load():
    probe = Gtk.Label()
    tints = "\n".join([
        f".sf-tile {{ background: {_rgba(probe, 'window_fg_color', 0.07)}; }}",
        f".sf-code {{ background: {_rgba(probe, 'window_fg_color', 0.08)}; }}",
        f".sf-callout-info {{ background: {_rgba(probe, 'accent_bg_color', 0.20)}; }}",
        f".sf-callout-success {{ background: {_rgba(probe, 'success_color', 0.18)}; }}",
        f".sf-callout-warning {{ background: {_rgba(probe, 'warning_color', 0.20)}; }}",
        f".sf-callout-error {{ background: {_rgba(probe, 'error_color', 0.20)}; }}",
        f".sf-error-note {{ background: {_rgba(probe, 'error_color', 0.16)}; }}",
    ])
    css = Gtk.CssProvider()
    css.load_from_string((paths.PACKAGE_DIR / "native" / "style.css").read_text() + "\n" + tints)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
