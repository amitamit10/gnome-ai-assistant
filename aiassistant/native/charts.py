"""Cairo charts as Gtk.DrawingArea subclasses. Colours come from the live GTK theme so they follow dark/light and the accent."""
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402

FALLBACK = {"accent_color": "#78aeed", "success_color": "#8ff0a4", "warning_color": "#f8e45c", "error_color": "#ff7b63",
            "blue_2": "#78aeed", "green_2": "#8ff0a4", "yellow_2": "#f8e45c", "red_2": "#ff7b63", "purple_2": "#dc8add",
            "orange_2": "#ffbe6f"}
SERIES = ("accent_color", "green_2", "orange_2", "purple_2", "red_2", "yellow_2")


def named(widget, name):
    """A theme colour (Gdk.RGBA) by its libadwaita name, with an Adwaita-dark fallback."""
    ok, rgba = widget.get_style_context().lookup_color(name)
    if ok:
        return rgba
    rgba = Gdk.RGBA()
    rgba.parse(FALLBACK.get(name, "#888888"))
    return rgba


def series_colour(widget, i):
    return named(widget, SERIES[i % len(SERIES)])


def set_src(cr, rgba, alpha=None):
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha if alpha is None else alpha)


def text(area, cr, s, x, y, rgba, size=0.85, align="left", bold=False, valign="top", alpha=0.75):
    """Draw `s` at (x, y); size is relative to the widget font; returns the text width."""
    lay = area.create_pango_layout(str(s))
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_scale_new(size))
    if bold:
        attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
    lay.set_attributes(attrs)
    w, h = lay.get_pixel_size()
    ox = x - (w if align == "right" else w / 2 if align == "center" else 0)
    oy = y - (h if valign == "bottom" else h / 2 if valign == "middle" else 0)
    cr.move_to(ox, oy)
    set_src(cr, rgba, alpha)
    PangoCairo.show_layout(cr, lay)
    return w


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def nice_ticks(lo, hi, n=4):
    """Round tick values covering [lo, hi]."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v < hi + step * 0.999:
        ticks.append(round(v, 10))
        v += step
        if len(ticks) > 10:
            break
    return ticks


def fmt(v, unit=""):
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        v = int(round(v))
    s = f"{v:,}" if isinstance(v, int) and abs(v) >= 10000 else (f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    return s + (unit or "")


class LineChart(Gtk.DrawingArea):
    """series: [{name, points: [[label, value], ...]}]; `values` draws the value above each point (few points)."""

    def __init__(self, series, unit="", height=170, values=False, fill=True):
        super().__init__()
        self.series = [s for s in series if s.get("points")]
        self.unit, self.show_values, self.fill = unit or "", values, fill
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, w, h):
        if not self.series:
            return
        fg = self.get_color()
        labels = [str(p[0]) for p in self.series[0]["points"]]
        n = len(labels)
        vals = [float(p[1]) for s in self.series for p in s["points"]]
        legend_h = 20 if len(self.series) > 1 else 0
        ticks = nice_ticks(min(vals), max(vals), 3 if h < 150 else 4)
        lo, hi = ticks[0], ticks[-1]
        ylab = max(len(fmt(t, self.unit)) for t in ticks) * 6.5 + 8
        left, right, top, bottom = ylab, 14, 10 + legend_h, 22
        pw, ph = w - left - right, h - top - bottom
        pad = 12  # keep the first/last point (and its value label) off the axis labels
        xs = lambda i: left + pad + ((pw - 2 * pad) * i / (n - 1) if n > 1 else (pw - 2 * pad) / 2)
        ys = lambda v: top + ph - (v - lo) / (hi - lo) * ph if hi > lo else top + ph / 2
        cr.set_line_width(1)
        for t in ticks:  # grid + y labels
            y = round(ys(t)) + 0.5
            set_src(cr, fg, 0.12)
            cr.move_to(left, y)
            cr.line_to(w - right, y)
            cr.stroke()
            text(self, cr, fmt(t, self.unit), left - 6, y, fg, 0.78, "right", valign="middle", alpha=0.6)
        stride = max(1, math.ceil(n / max(2, int(pw // 52))))
        for i in range(0, n, stride):
            text(self, cr, labels[i], xs(i), h - bottom + 5, fg, 0.78, "center", alpha=0.6)
        for si, s in enumerate(self.series):
            col = series_colour(self, si)
            pts = [(xs(i), ys(float(p[1]))) for i, p in enumerate(s["points"][:n])]
            if self.fill and si == 0 and len(self.series) == 1 and len(pts) > 1:
                import cairo
                grad = cairo.LinearGradient(0, top, 0, top + ph)
                grad.add_color_stop_rgba(0, col.red, col.green, col.blue, 0.28)
                grad.add_color_stop_rgba(1, col.red, col.green, col.blue, 0.0)
                cr.move_to(pts[0][0], top + ph)
                for x, y in pts:
                    cr.line_to(x, y)
                cr.line_to(pts[-1][0], top + ph)
                cr.close_path()
                cr.set_source(grad)
                cr.fill()
            set_src(cr, col, 1)
            cr.set_line_width(2.2)
            cr.set_line_join(1)
            cr.set_line_cap(1)
            for k, (x, y) in enumerate(pts):
                (cr.move_to if k == 0 else cr.line_to)(x, y)
            cr.stroke()
            if n <= 14:
                for k, (x, y) in enumerate(pts):
                    set_src(cr, col, 1)
                    cr.arc(x, y, 3.2, 0, 2 * math.pi)
                    cr.fill()
                    if self.show_values and len(self.series) == 1:
                        text(self, cr, fmt(float(s["points"][k][1]), self.unit), x, y - 6, fg, 0.8, "center", valign="bottom", alpha=0.9)
        if legend_h:
            x = left
            for si, s in enumerate(self.series):
                col = series_colour(self, si)
                set_src(cr, col, 1)
                cr.arc(x + 4, 10, 4, 0, 2 * math.pi)
                cr.fill()
                x += 14 + text(self, cr, s.get("name", ""), x + 12, 10, fg, 0.85, valign="middle", alpha=0.85)


class BarChart(Gtk.DrawingArea):
    ROW = 30

    def __init__(self, bars, unit=""):
        super().__init__()
        self.bars, self.unit = bars, unit or ""
        self.set_content_height(max(1, len(bars)) * self.ROW)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, w, h):
        if not self.bars:
            return
        fg = self.get_color()
        top = max(float(b["value"]) for b in self.bars) or 1
        lab = min(w * 0.34, max(len(str(b["label"])) for b in self.bars) * 7.5 + 8)
        valw = max(len(fmt(b["value"], self.unit)) for b in self.bars) * 7 + 10
        bw = w - lab - valw - 4
        for i, b in enumerate(self.bars):
            y = i * self.ROW
            text(self, cr, b["label"], 0, y + self.ROW / 2, fg, 0.95, valign="middle", alpha=0.9)
            set_src(cr, fg, 0.10)
            rounded(cr, lab, y + 7, bw, self.ROW - 14, 4)
            cr.fill()
            set_src(cr, series_colour(self, 0), 1)
            rounded(cr, lab, y + 7, max(4, bw * float(b["value"]) / top), self.ROW - 14, 4)
            cr.fill()
            text(self, cr, fmt(b["value"], self.unit), w, y + self.ROW / 2, fg, 0.9, "right", valign="middle", alpha=0.85)


class Donut(Gtk.DrawingArea):
    def __init__(self, segments, center="", size=150):
        super().__init__()
        self.segments = [s for s in segments if float(s["value"]) > 0]
        self.center = center
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, w, h):
        fg = self.get_color()
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 4
        total = sum(float(s["value"]) for s in self.segments) or 1
        a = -math.pi / 2
        cr.set_line_width(r * 0.34)
        gap = 0.03 if len(self.segments) > 1 else 0
        for i, s in enumerate(self.segments):
            sweep = 2 * math.pi * float(s["value"]) / total
            set_src(cr, series_colour(self, i), 1)
            g = min(gap, sweep / 4)  # a tiny slice must still be visible
            cr.arc(cx, cy, r * 0.83, a + g, a + sweep - g)
            cr.stroke()
            a += sweep
        if self.center:
            text(self, cr, self.center, cx, cy, fg, 0.95, "center", bold=True, valign="middle", alpha=0.95)


class Ring(Gtk.DrawingArea):
    """A 270-degree gauge ring with the value in the middle."""

    def __init__(self, frac, label, colour_name, size=112):
        super().__init__()
        self.frac, self.label, self.colour_name = max(0.0, min(1.0, frac)), label, colour_name
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, w, h):
        fg = self.get_color()
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 8
        start, span = 0.75 * math.pi, 1.5 * math.pi
        cr.set_line_width(10)
        cr.set_line_cap(1)
        set_src(cr, fg, 0.13)
        cr.arc(cx, cy, r, start, start + span)
        cr.stroke()
        if self.frac > 0:
            set_src(cr, named(self, self.colour_name), 1)
            cr.arc(cx, cy, r, start, start + span * self.frac)
            cr.stroke()
        text(self, cr, self.label, cx, cy, fg, 1.45, "center", bold=True, valign="middle", alpha=0.95)
