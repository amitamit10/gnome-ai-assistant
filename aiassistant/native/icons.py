"""Resolve the icon names widgets use (ui/icons.py) to icons that exist in the user's current icon theme."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from ..ui import icons as names  # noqa: E402

_cache = {}


def resolve(name):
    """A symbolic icon name present in the theme, or None."""
    if not name:
        return None
    if name in _cache:
        return _cache[name]
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    found = None
    for cand in [*names.NAMES.get(name, []), f"{name}-symbolic", name]:
        if theme.has_icon(cand):
            found = cand
            break
    _cache[name] = found
    return found


def image(name, size=16):
    """A Gtk.Image for `name`, or None when the theme has nothing suitable."""
    icon = resolve(name)
    if not icon:
        return None
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(size)
    img.set_size_request(size + 2, size + 2)  # same footprint for every icon so rows line up
    return img


def weather_icon(condition):
    c = (condition or "").lower()
    for words, icon in ((("thunder", "storm"), "weather-storm-symbolic"), (("snow", "sleet", "ice"), "weather-snow-symbolic"),
                        (("rain", "shower", "drizzle"), "weather-showers-symbolic"), (("fog", "mist", "haze"), "weather-fog-symbolic"),
                        (("partly", "mainly clear", "few cloud", "scattered"), "weather-few-clouds-symbolic"),
                        (("overcast", "cloud"), "weather-overcast-symbolic"), (("clear", "sun"), "weather-clear-symbolic")):
        if any(w in c for w in words):
            return icon
    return "weather-clear-symbolic"
