import json

import pytest

from aiassistant.tools import device, files, registry, weather, web
from aiassistant.ui import widgets

FORECAST = {"place": "Jerusalem, IL", "current": {"temp_c": 24, "feels_like_c": 23, "humidity_pct": 49, "wind_kmh": 6, "condition": "clear sky"},
            "next_24h": [{"time": f"{h:02d}:00", "temp_c": 20 + h % 5, "rain_pct": 0} for h in range(24)],
            "daily": [{"date": f"2026-10-2{i}", "min_c": 14, "max_c": 25, "rain_pct": 0, "condition": "clear sky"} for i in range(1, 6)]}


def test_weather_shows_a_card_automatically(monkeypatch):
    monkeypatch.setattr(weather, "forecast", lambda city: FORECAST)
    ctx = registry.Context()
    r = registry.call(ctx, "get_weather", {"city": "Jerusalem"})
    assert len(ctx.shown) == 1 and ctx.shown[0]["widget"] == "weather" and ctx.shown[0]["data"]["place"] == "Jerusalem, IL"
    assert len(ctx.shown[0]["data"]["hourly"]) and len(ctx.shown[0]["data"]["daily"]) == 5
    assert "already displayed" in r["note"]


def test_weather_error_shows_nothing(monkeypatch):
    monkeypatch.setattr(weather, "forecast", lambda city: {"error": "city not found: x"})
    ctx = registry.Context()
    assert "error" in registry.call(ctx, "get_weather", {"city": "x"}) and not ctx.shown


@pytest.mark.parametrize("topic,payload,marker", [
    ("battery", {"present": True, "percent": 53, "status": "Discharging", "time_remaining_min": 90}, '"title": "Battery"'),
    ("battery", {"present": True, "percent": 36, "status": "Charging", "time_remaining_min": 52}, "about 52 min to full"),
    ("memory", {"total_gb": 15, "available_gb": 2, "used_pct": 86}, '"title": "Memory"'),
    ("wifi", {"connected": True, "ssid": "Home", "signal_pct": 50, "security": "WPA2", "rate": "65 Mbit/s"}, '"value": "Home"'),
    ("wifi", {"connected": False}, "Not connected"),
    ("system", {"os": "Zorin OS", "kernel": "7.0", "session": "wayland", "desktop": "GNOME", "gnome_shell": "46"}, "Zorin OS"),
])
def test_device_info_gets_an_automatic_widget(monkeypatch, topic, payload, marker):
    monkeypatch.setattr(device, "get", lambda t: payload)
    ctx = registry.Context()
    r = registry.call(ctx, "get_device_info", {"topic": topic})
    assert len(ctx.shown) == 1 and marker in json.dumps(ctx.shown[0]["data"])
    assert "already displayed" in json.dumps(r)


def test_device_summary_widget_has_cards(monkeypatch):
    summary = {"battery": {"present": True, "percent": 40, "status": "Charging"}, "wifi": {"connected": True, "ssid": "H", "signal_pct": 60},
               "memory": {"used_pct": 50, "available_gb": 7}, "disk": {"filesystems": [{"free_gb": 40, "used_pct": 60}]}, "uptime": {"up": "1d"}}
    monkeypatch.setattr(device, "get", lambda t: summary)
    ctx = registry.Context()
    registry.call(ctx, "get_device_info", {"topic": "summary"})
    assert "Uptime" in json.dumps(ctx.shown[0]["data"])


def test_search_files_shows_a_grid_without_sending_thumbnails_to_the_model(monkeypatch):
    items = [{"kind": "image", "name": "a.png", "path": "~/a.png", "thumb": "data:image/jpeg;base64,AAAA"},
             {"kind": "text", "name": "n.md", "path": "~/n.md", "snippet": "hello"}]
    monkeypatch.setattr(files, "search", lambda q: ({"results": [{"kind": "image", "name": "a.png"}]}, {"title": "Files", "items": items}))
    ctx = registry.Context()
    r = registry.call(ctx, "search_files", {"query": "x"})
    assert len(ctx.shown) == 1 and "AAAA" in json.dumps(ctx.shown[0]["data"])
    assert "AAAA" not in json.dumps(r)


def test_web_search_lists_sources(monkeypatch):
    monkeypatch.setattr(web, "search", lambda q: {"answer": "42", "sources": [{"title": "T", "url": "https://example.com/a"}]})
    ctx = registry.Context()
    registry.call(ctx, "web_search", {"query": "q"})
    assert "example.com" in json.dumps(ctx.shown[0]["data"])


def test_show_widget_validates_and_explains():
    ctx = registry.Context()
    bad = registry.call(ctx, "show_widget", {"widget": "gauge", "data_json": "{}"})
    assert "required property" in bad["error"] and not ctx.shown
    assert "error" in registry.call(ctx, "show_widget", {"widget": "gauge", "data_json": "not json"})
    assert registry.call(ctx, "show_widget", {"widget": "gauge", "data_json": json.dumps({"value": 5})})["ok"]


def test_show_widgets_arranges_rows():
    ctx = registry.Context()
    items = [{"widget": "gauge", "data": {"value": i}} for i in (10, 20, 30)]
    registry.call(ctx, "show_widgets", {"items_json": json.dumps(items), "columns": 2})
    assert [w["row"] for w in ctx.shown] == [1, 1, 2]
    ctx2 = registry.Context()
    registry.call(ctx2, "show_widgets", {"items_json": json.dumps(items)})
    assert [w["row"] for w in ctx2.shown] == [1, 2, 3]


def test_there_is_no_way_to_make_html_widgets_any_more():
    names = {d["name"] for d in registry.DECLARATIONS}
    assert "create_widget" not in names and "find_icon" not in names
    assert "unknown tool" in registry.call(registry.Context(), "create_widget", {})["error"]


def test_unknown_tool():
    assert "unknown tool" in registry.call(registry.Context(), "rm_rf", {})["error"]


def test_every_declared_tool_is_dispatchable():
    for d in registry.DECLARATIONS:
        assert d["name"] in registry.LABELS
