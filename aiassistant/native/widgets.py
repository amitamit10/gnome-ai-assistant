"""Native GTK builders for the widget library: one function per widget name, `build(name, data, ctx) -> Gtk.Widget`.

`ctx` supplies the actions a widget may trigger: send(text), open_url(url), open_file(path), copy(text). Descriptions and data
contracts live in data/library/<name>.json (ui/widgets.py); every JSON file needs a builder here.
"""
import base64

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import charts, icons  # noqa: E402
from .markup import to_pango  # noqa: E402

BUILDERS = {}


def builder(fn):
    BUILDERS[fn.__name__.removeprefix("w_")] = fn
    return fn


# ---------------------------------------------------------------- helpers
def label(text, css=(), wrap=True, selectable=False, markup=False, xalign=0.0, ellipsize=False):
    lb = Gtk.Label(xalign=xalign, wrap=wrap, selectable=selectable, use_markup=markup)
    lb.set_label(str(text))
    if wrap:
        lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    for c in ([css] if isinstance(css, str) else css):
        lb.add_css_class(c)
    return lb


def box(vertical=True, spacing=6, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in children:
        if c is not None:
            b.append(c)
    return b


def card(title=None, *children, spacing=10):
    """The standard widget frame: a libadwaita card with an optional title."""
    outer = box(True, spacing)
    outer.add_css_class("card")
    outer.add_css_class("sf-card")
    if title:
        outer.append(label(title, ["heading"], wrap=False, ellipsize=True))
    for c in children:
        if c is not None:
            outer.append(c)
    return outer


def icon_label(icon_name, text, css=()):
    img = icons.image(icon_name, 16)
    return box(False, 8, img, label(text, css)) if img else label(text, css)


def tint(widget, kind):
    widget.add_css_class(f"sf-{kind}")
    return widget


def grid(columns, items, spacing=8, homogeneous=True):
    g = Gtk.Grid(column_spacing=spacing, row_spacing=spacing, column_homogeneous=homogeneous)
    for i, it in enumerate(items):
        it.set_hexpand(True)
        g.attach(it, i % columns, i // columns, 1, 1)
    return g


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _scrolled_h(child):
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_propagate_natural_height(True)
    sw.set_child(child)
    return sw


# ---------------------------------------------------------------- widgets
@builder
def w_gauge(d, ctx):
    lo, hi = _num(d.get("min", 0)), _num(d.get("max", 100)) or 100
    v = _num(d.get("value"))
    frac = (v - lo) / ((hi - lo) or 1)
    warn, bad = d.get("warn_at"), d.get("bad_at")
    if d.get("low_is_bad"):
        colour = "error_color" if bad is not None and v <= bad else "warning_color" if warn is not None and v <= warn else "success_color"
    else:
        colour = "error_color" if bad is not None and v >= bad else "warning_color" if warn is not None and v >= warn else "accent_color"
    unit = d.get("unit", "%")
    ring = charts.Ring(frac, charts.fmt(v, "") + (unit if len(unit) <= 2 else ""), colour)
    side = box(True, 3, label(d.get("label", ""), ["title-3"]) if d.get("label") else None,
               label(d.get("sub", ""), ["dim-label"]) if d.get("sub") else None)
    side.set_valign(Gtk.Align.CENTER)
    side.set_hexpand(True)
    return card(d.get("title"), box(False, 16, ring, side))


@builder
def w_line_chart(d, ctx):
    return card(d.get("title"), charts.LineChart(d.get("series", []), d.get("unit", ""), height=190))


@builder
def w_bar_chart(d, ctx):
    return card(d.get("title"), charts.BarChart(d.get("bars", []), d.get("unit", "")))


@builder
def w_donut_chart(d, ctx):
    segs = d.get("segments", [])
    total = sum(_num(s["value"]) for s in segs) or 1
    legend = box(True, 6)
    legend.set_valign(Gtk.Align.CENTER)
    for i, s in enumerate(segs):
        dot = Gtk.DrawingArea()
        dot.set_content_width(10)
        dot.set_content_height(10)
        dot.set_valign(Gtk.Align.CENTER)

        def draw(area, cr, w, h, i=i):
            charts.set_src(cr, charts.series_colour(area, i), 1)
            charts.rounded(cr, 0, 0, w, h, 3)
            cr.fill()
        dot.set_draw_func(draw)
        pct = round(100 * _num(s["value"]) / total)
        legend.append(box(False, 8, dot, label(s["label"], wrap=False), label(f"{charts.fmt(s['value'], d.get('unit', ''))}  ·  {pct}%", ["dim-label"], wrap=False)))
    return card(d.get("title"), box(False, 18, charts.Donut(segs, d.get("center", "")), legend))


@builder
def w_weather(d, ctx):
    unit = d.get("unit", "°C")
    head = box(False, 14)
    big = icons.weather_icon(d.get("condition"))
    img = Gtk.Image.new_from_icon_name(big)
    img.set_pixel_size(56)
    head.append(img)
    info = box(True, 2, label(f"{d.get('temp')}{unit}", ["title-1"], wrap=False),
               label(str(d.get("condition", "")).capitalize(), ["heading"], wrap=False))
    info.set_valign(Gtk.Align.CENTER)
    head.append(info)
    facts = box(True, 2, label(f"Feels like {d.get('feels_like')}{unit}", ["dim-label"], wrap=False),
                label(f"Humidity {d.get('humidity')}%", ["dim-label"], wrap=False),
                label(f"Wind {d.get('wind')} km/h", ["dim-label"], wrap=False))
    facts.set_halign(Gtk.Align.END)
    facts.set_hexpand(True)
    facts.set_valign(Gtk.Align.CENTER)
    head.append(facts)
    parts = [box(True, 2, label(d.get("place", ""), ["heading"], wrap=False, ellipsize=True)), head]
    hourly = d.get("hourly") or []
    if hourly:
        chart = charts.LineChart([{"name": "Temperature", "points": [[h["t"], h["temp"]] for h in hourly]}], unit="°", height=130,
                                 values=len(hourly) <= 9)
        parts.append(chart)
    daily = d.get("daily") or []
    if daily:
        cols = []
        for day in daily[:7]:
            ico = Gtk.Image.new_from_icon_name(icons.weather_icon(day.get("condition")))
            ico.set_pixel_size(24)
            temps = box(True, 0, label(f"{day.get('max')}°", ["heading"], wrap=False, xalign=0.5),
                        label(f"{day.get('min')}°", ["dim-label"], wrap=False, xalign=0.5))
            col = box(True, 4, label(day.get("day", ""), ["caption-heading"], wrap=False, xalign=0.5), ico, temps)
            if day.get("rain") not in (None, 0):
                col.append(label(f"{day['rain']}%", ["caption", "accent"], wrap=False, xalign=0.5))
            cols.append(col)
        row = Gtk.Box(spacing=4, homogeneous=True)
        for c in cols:
            row.append(c)
        parts.append(Gtk.Separator())
        parts.append(row)
    return card(None, *parts, spacing=12)


@builder
def w_stat_cards(d, ctx):
    tiles = []
    for c in d.get("cards", []):
        trend = {"up": ("▲", "success"), "down": ("▼", "error")}.get(c.get("trend"))
        head = box(False, 6, icons.image(c.get("icon"), 14), label(c.get("label", ""), ["caption", "dim-label"], wrap=False, ellipsize=True))
        tile = box(True, 2, head, label(c.get("value", ""), ["title-3"], wrap=False, ellipsize=True))
        if c.get("sub") or trend:
            sub = box(False, 4)
            if trend:
                sub.append(tint(label(trend[0], ["caption"], wrap=False), trend[1]))
            sub.append(label(c.get("sub", ""), ["caption", "dim-label"], wrap=False, ellipsize=True))
            tile.append(sub)
        tile.add_css_class("sf-tile")
        tiles.append(tile)
    return card(d.get("title"), grid(min(3, max(1, len(tiles))), tiles))


@builder
def w_table(d, ctx):
    cols = d.get("columns", [])
    g = Gtk.Grid(column_spacing=18, row_spacing=7)
    for c, name in enumerate(cols):
        h = label(name, ["caption-heading", "dim-label"], wrap=False)
        h.set_hexpand(True)
        g.attach(h, c, 0, 1, 1)
    g.attach(Gtk.Separator(), 0, 1, max(1, len(cols)), 1)
    for r, row in enumerate(d.get("rows", [])):
        for c, cell in enumerate(row):
            lb = label(cell, selectable=True)
            lb.set_hexpand(True)
            g.attach(lb, c, r + 2, 1, 1)
    return card(d.get("title"), g)


@builder
def w_details(d, ctx):
    g = Gtk.Grid(column_spacing=14, row_spacing=7)
    for r, row in enumerate(d.get("rows", [])):
        ico = icons.image(row.get("icon"), 16)
        left = box(False, 8, ico, label(row.get("label", ""), ["dim-label"], wrap=False))
        g.attach(left, 0, r, 1, 1)
        v = label(row.get("value", ""), selectable=True)
        v.set_hexpand(True)
        g.attach(v, 1, r, 1, 1)
    return card(d.get("title"), g)


@builder
def w_callout(d, ctx):
    kind = d.get("kind", "info") if d.get("kind") in ("info", "success", "warning", "error") else "info"
    ico = icons.image({"info": "info", "success": "check", "warning": "warning", "error": "error"}[kind], 20)
    body = box(True, 2, label(d["title"], ["heading"]) if d.get("title") else None, label(d.get("text", ""), selectable=True))
    body.set_hexpand(True)
    out = box(False, 12, ico, body)
    out.add_css_class("sf-callout")
    out.add_css_class(f"sf-callout-{kind}")
    return out


@builder
def w_checklist(d, ctx):
    items = box(True, 4)
    for it in d.get("items", []):
        chk = Gtk.CheckButton()
        lb = label(it.get("text", ""))
        chk.set_child(lb)
        chk.set_active(bool(it.get("done")))

        def toggled(btn, lb=lb, text=it.get("text", "")):
            esc = GLib.markup_escape_text(text)
            lb.set_use_markup(btn.get_active())
            lb.set_label(f"<s>{esc}</s>" if btn.get_active() else text)
            lb.set_opacity(0.55 if btn.get_active() else 1.0)
        chk.connect("toggled", toggled)
        toggled(chk)
        items.append(chk)
    return card(d.get("title"), items)


@builder
def w_choices(d, ctx):
    fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, column_spacing=6, row_spacing=6,
                     max_children_per_line=6)
    for o in d.get("options", []):
        content = box(False, 6, icons.image(o.get("icon"), 14), label(o.get("label", ""), wrap=False))
        b = Gtk.Button(child=content)
        b.add_css_class("pill")
        b.connect("clicked", lambda _b, text=o.get("send") or o.get("label", ""): ctx.send(text))
        fb.append(b)
    return card(d.get("title"), fb) if d.get("title") else fb


@builder
def w_code_block(d, ctx):
    code = d.get("code", "")
    body = label(code, ["monospace"], wrap=False, selectable=True)
    body.add_css_class("sf-code")
    copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy")
    copy.add_css_class("flat")
    copy.set_valign(Gtk.Align.CENTER)
    copy.connect("clicked", lambda _b: ctx.copy(code))
    head = box(False, 6, label(d.get("title") or d.get("language", ""), ["caption-heading", "dim-label"], wrap=False))
    head.get_first_child().set_hexpand(True)
    head.append(copy)
    return card(None, head, _scrolled_h(body), spacing=4)


@builder
def w_link_list(d, ctx):
    rows = box(True, 2)
    any_icon = any(icons.resolve(it.get("icon")) for it in d.get("items", []))
    for it in d.get("items", []):
        spacer = Gtk.Box()
        spacer.set_size_request(18, 18)
        text = box(True, 1, label(it.get("title", ""), ["heading"] + (["accent"] if it.get("url") else [])),
                   label(it["description"], ["dim-label"]) if it.get("description") else None,
                   label(it["meta"], ["caption", "dim-label"], wrap=False, ellipsize=True) if it.get("meta") else None)
        text.set_hexpand(True)
        row = box(False, 10, icons.image(it.get("icon"), 18) or (spacer if any_icon else None), text)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        if it.get("url"):
            b = Gtk.Button(child=row)
            b.add_css_class("flat")
            b.add_css_class("sf-row")
            b.connect("clicked", lambda _b, url=it["url"]: ctx.open_url(url))
            rows.append(b)
        else:
            row.set_margin_start(6)  # the same inset a button row has
            rows.append(row)
    return card(d.get("title"), rows)


def _texture_from_data_uri(uri):
    try:
        raw = base64.b64decode(uri.split(",", 1)[1])
        loader = GdkPixbuf.PixbufLoader()
        loader.write(raw)
        loader.close()
        return Gdk.Texture.new_for_pixbuf(loader.get_pixbuf())
    except Exception:
        return None


@builder
def w_file_results(d, ctx):
    tiles = []
    for it in d.get("items", []):
        kind = it.get("kind", "text")
        if kind == "image" and it.get("thumb"):
            tex = _texture_from_data_uri(it["thumb"])
        else:
            tex = None
        if tex:
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(-1, 96)
            pic.set_can_shrink(True)
            pic.add_css_class("sf-thumb")
            top = pic
        else:
            ico = Gtk.Image.new_from_icon_name({"video": "video-x-generic-symbolic", "image": "image-x-generic-symbolic"}.get(kind, "text-x-generic-symbolic"))
            ico.set_pixel_size(32)
            ico.set_margin_top(10)
            ico.set_halign(Gtk.Align.START)
            top = ico
        parts = [top, label(it.get("name", ""), ["caption-heading"], wrap=False, ellipsize=True)]
        if it.get("snippet"):
            sn = label(it["snippet"], ["caption", "dim-label"], wrap=True)
            sn.set_lines(3)
            sn.set_ellipsize(Pango.EllipsizeMode.END)
            parts.append(sn)
        b = Gtk.Button(child=box(True, 4, *parts))
        b.add_css_class("flat")
        b.add_css_class("sf-row")
        b.set_tooltip_text(it.get("path", ""))
        b.connect("clicked", lambda _b, p=it.get("path", ""): ctx.open_file(p))
        tiles.append(b)
    return card(d.get("title"), grid(3, tiles, homogeneous=True))


@builder
def w_timeline(d, ctx):
    rows = box(True, 0)
    events = d.get("events", [])
    for i, e in enumerate(events):
        dot = Gtk.DrawingArea()
        dot.set_content_width(14)
        dot.set_vexpand(True)

        def draw(area, cr, w, h, last=(i == len(events) - 1)):
            fg = area.get_color()
            charts.set_src(cr, fg, 0.2)
            if not last:
                cr.rectangle(w / 2 - 1, 12, 2, h - 8)
                cr.fill()
            charts.set_src(cr, charts.named(area, "accent_color"), 1)
            cr.arc(w / 2, 8, 4.5, 0, 6.2832)
            cr.fill()
        dot.set_draw_func(draw)
        text = box(True, 1, label(e.get("title", ""), ["heading"]), label(e["description"], ["dim-label"]) if e.get("description") else None)
        text.set_margin_bottom(10)
        text.set_hexpand(True)
        t = label(e.get("time", ""), ["dim-label", "numeric"], wrap=False, xalign=1.0)
        t.set_size_request(54, -1)
        rows.append(box(False, 10, t, dot, text))
    return card(d.get("title"), rows)


@builder
def w_timer(d, ctx):
    total = int(_num(d.get("seconds"), 60))
    state = {"left": total, "tid": 0}
    face = label("", ["title-1", "numeric"], wrap=False, xalign=0.5)
    play = Gtk.Button(icon_name="media-playback-start-symbolic")
    play.add_css_class("circular")
    play.add_css_class("suggested-action")
    reset = Gtk.Button(icon_name="view-refresh-symbolic")
    reset.add_css_class("circular")

    def show():
        m, s = divmod(max(0, state["left"]), 60)
        face.set_label(f"{m // 60}:{m % 60:02d}:{s:02d}" if m >= 60 else f"{m:02d}:{s:02d}")

    def tick():
        state["left"] -= 1
        show()
        if state["left"] <= 0:
            state["tid"] = 0
            play.set_icon_name("media-playback-start-symbolic")
            face.add_css_class("error")
            return False
        return True

    def toggle(_b=None):
        if state["tid"]:
            GLib.source_remove(state["tid"])
            state["tid"] = 0
            play.set_icon_name("media-playback-start-symbolic")
        else:
            if state["left"] <= 0:
                state["left"] = total
                face.remove_css_class("error")
            state["tid"] = GLib.timeout_add_seconds(1, tick)
            play.set_icon_name("media-playback-pause-symbolic")
            show()

    def do_reset(_b):
        if state["tid"]:
            GLib.source_remove(state["tid"])
            state["tid"] = 0
        state["left"] = total
        face.remove_css_class("error")
        play.set_icon_name("media-playback-start-symbolic")
        show()

    play.connect("clicked", toggle)
    reset.connect("clicked", do_reset)
    show()
    buttons = box(False, 8, play, reset)
    buttons.set_halign(Gtk.Align.CENTER)
    out = card(d.get("title"), face, label(d.get("label", ""), ["dim-label"], xalign=0.5) if d.get("label") else None, buttons)

    def gone(_w):
        if state["tid"]:
            GLib.source_remove(state["tid"])
            state["tid"] = 0
    out.connect("destroy", gone)
    if d.get("autostart"):
        GLib.idle_add(lambda: toggle() or False)
    return out


def build(name, data, ctx):
    """Build the widget `name` from `data`; a failing builder becomes a small error note instead of breaking the chat."""
    fn = BUILDERS.get(name)
    if not fn:
        return label(f"(unknown widget: {name})", ["dim-label"])
    try:
        return fn(data, ctx)
    except Exception as e:
        return label(f"(could not draw {name}: {type(e).__name__})", ["dim-label"])
