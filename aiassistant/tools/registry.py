"""Tool declarations (for the LLM) and dispatch. Tools can show widgets; several attach one automatically.

A shown widget is just {"widget": name, "data": {...}, "row": n}; the chat window draws it natively.

Automatic widgets (no LLM tokens, instant): weather -> weather card, search_files -> thumbnail grid,
get_device_info -> gauges/cards, web_search -> source list. The model only adds a short sentence.
"""
import json

from ..ui import widgets
from . import device, files, weather, web


class Context:
    """Per-question state: the widgets produced so far (each {"widget": name, "data": {...}, "row": n})."""

    def __init__(self):
        self.shown = []
        self._row = 0

    def add(self, name, data, same_row=False):
        """Queue a library widget. Raises ValueError with a fixable message when the data does not fit its schema."""
        err = widgets.validate_data(name, data)
        if err:
            raise ValueError(err)
        if not same_row:
            self._row += 1
        self.shown.append({"widget": name, "data": data, "row": self._row})

    def items(self):
        return list(self.shown)


def _decl(name, description, props=None, required=()):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}


S = {"type": "string"}
DECLARATIONS = [
    _decl("get_weather", "Current weather, next 24 hours and 5-day forecast for a city. Also displays the weather card.",
          {"city": S}, ["city"]),
    _decl("web_search", "Search the web (Google) and return a short sourced answer. Sources are displayed automatically.",
          {"query": S}, ["query"]),
    _decl("search_files", "Semantic search over the user's own files: notes, docs, screenshots, videos. Displays a thumbnail grid.",
          {"query": S}, ["query"]),
    _decl("get_device_info", "Read-only information about this computer (wifi, battery, bluetooth, audio, disk, memory, cpu, location...). "
          "Gauges/cards are displayed automatically for most topics.",
          {"topic": {"type": "string", "enum": ["summary"] + list(device.TOPICS)}}, ["topic"]),
    _decl("show_widget", "Display one widget from the library.",
          {"widget": S, "data_json": {"type": "string", "description": "JSON object matching the widget's data schema"}},
          ["widget", "data_json"]),
    _decl("show_widgets", "Display several library widgets at once, optionally side by side (columns 2 or 3).",
          {"items_json": {"type": "string", "description": 'JSON array like [{"widget":"gauge","data":{...}}, ...]'},
           "columns": {"type": "integer", "description": "1 (stacked, default), 2 or 3 per row"}}, ["items_json"]),
]

LABELS = {"get_weather": "Checking the weather", "web_search": "Searching the web", "search_files": "Searching your files",
          "get_device_info": "Reading device info", "show_widget": "Drawing",
          "show_widgets": "Drawing"}


# ---------------- automatic widgets ----------------
def _device_widget(topic, d):
    """(widget, data) for a get_device_info result, or None."""
    if "error" in d:
        return None
    if topic == "battery" and d.get("present"):
        mins = d.get("time_remaining_min")
        when = f"{mins // 60} h {mins % 60} min" if mins and mins >= 60 else f"{mins} min"
        sub = (f"about {when} to full" if d.get("status") == "Charging" else f"about {when} left") if mins else ""
        return "gauge", {"title": "Battery", "value": d["percent"], "label": d.get("status", ""), "sub": sub,
                         "warn_at": 30, "bad_at": 15, "low_is_bad": True}
    if topic == "memory":
        return "gauge", {"title": "Memory", "value": d["used_pct"], "label": f"{d['used_pct']}% used",
                         "sub": f"{d['available_gb']} GB free of {d['total_gb']} GB", "warn_at": 80, "bad_at": 92}
    if topic == "disk" and d.get("filesystems"):
        f = d["filesystems"][0]
        return "gauge", {"title": "Disk", "value": f["used_pct"], "label": f["path"], "sub": f"{f['free_gb']} GB free of {f['total_gb']} GB",
                         "warn_at": 80, "bad_at": 92}
    if topic == "cpu":
        return "gauge", {"title": "CPU", "value": d["usage_pct"], "label": d["model"], "sub": f"load {d['load_avg'][0]}", "warn_at": 70, "bad_at": 90}
    if topic == "wifi":
        if not d.get("connected"):
            return "callout", {"kind": "warning", "title": "Wi-Fi", "text": "Not connected to a Wi-Fi network."}
        return "stat_cards", {"title": "Wi-Fi", "cards": [
            {"icon": "wifi", "label": "Network", "value": d["ssid"], "sub": d["security"]},
            {"icon": "signal", "label": "Signal", "value": f"{d['signal_pct']}%"},
            {"icon": "gauge", "label": "Speed", "value": d["rate"]}]}
    if topic == "audio":
        cards = []
        for key, label, ic in (("output", "Speakers", "volume-2"), ("microphone", "Microphone", "mic")):
            v = d.get(key)
            if v:
                cards.append({"icon": ic, "label": label, "value": f"{v['volume_pct']}%", "sub": "muted" if v["muted"] else "on"})
        return ("stat_cards", {"title": "Audio", "cards": cards}) if cards else None
    if topic == "system":
        rows = [{"label": k, "value": str(v)} for k, v in (("System", d.get("os")), ("Kernel", d.get("kernel")), ("Session", d.get("session")),
                                                          ("Desktop", d.get("desktop")), ("Shell", d.get("gnome_shell"))) if v]
        return "details", {"title": "This computer", "rows": rows}
    if topic == "summary":
        cards = []
        b = d.get("battery", {})
        if b.get("present"):
            cards.append({"icon": "battery-full", "label": "Battery", "value": f"{b['percent']}%", "sub": b.get("status", ""),
                          "trend": "down" if b.get("status") == "Discharging" else "up"})
        w = d.get("wifi", {})
        cards.append({"icon": "wifi", "label": "Wi-Fi", "value": w.get("ssid", "offline") if w.get("connected") else "offline",
                      "sub": f"{w['signal_pct']}% signal" if w.get("connected") else ""})
        m = d.get("memory", {})
        cards.append({"icon": "memory-stick", "label": "Memory", "value": f"{m.get('used_pct')}%", "sub": f"{m.get('available_gb')} GB free"})
        fs = (d.get("disk", {}).get("filesystems") or [{}])[0]
        cards.append({"icon": "hard-drive", "label": "Disk", "value": f"{fs.get('free_gb')} GB free", "sub": f"{fs.get('used_pct')}% used"})
        cards.append({"icon": "clock", "label": "Uptime", "value": d.get("uptime", {}).get("up", "")})
        return "stat_cards", {"title": "Status", "cards": cards}
    return None


def call(ctx, name, a):
    """Run one tool. Returns a JSON-able result for the model; widgets go to ctx."""
    if name == "get_weather":
        w = weather.forecast(a["city"])
        if "error" in w:
            return w
        ctx.add("weather", weather.widget_data(w))
        d = w["daily"]
        return {"place": w["place"], "current": w["current"], "today": d[0], "tomorrow": d[1] if len(d) > 1 else None,
                "note": "A weather card with the 24h chart and 5-day forecast is already displayed. Reply with 1-2 sentences."}
    if name == "web_search":
        r = web.search(a["query"])
        links = [{"title": s["title"] or s["url"], "url": s["url"], "meta": s["url"].split("/")[2] if "//" in s["url"] else ""}
                 for s in r["sources"] if s.get("url")]
        if links:
            ctx.add("link_list", {"title": "Sources", "items": links})
        return r
    if name == "search_files":
        result, data = files.search(a["query"])
        if data["items"]:
            ctx.add("file_results", data)
        return result
    if name == "get_device_info":
        topic = a.get("topic", "summary")
        d = device.get(topic)
        w = _device_widget(topic, d)
        if w:
            ctx.add(*w)
            d = {**d, "_note": "a visual widget for this is already displayed; reply with one short sentence"}
        return d
    if name == "show_widget":
        try:
            ctx.add(a.get("widget", ""), json.loads(a.get("data_json", "{}")))
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        return {"ok": True, "note": "widget displayed; add at most 1-2 sentences"}
    if name == "show_widgets":
        try:
            items = json.loads(a.get("items_json", "[]"))
            cols = max(1, min(3, int(a.get("columns") or 1)))
            if not isinstance(items, list) or not items:
                return {"error": "items_json must be a non-empty JSON array of {widget, data}"}
            for n, it in enumerate(items[:6]):
                ctx.add(it.get("widget", ""), it.get("data", {}), same_row=(cols > 1 and n % cols != 0))
        except (ValueError, TypeError, AttributeError) as e:
            return {"error": str(e)}
        return {"ok": True, "shown": len(items[:6]), "note": "widgets displayed; add at most 1-2 sentences"}
    return {"error": f"unknown tool {name}"}
