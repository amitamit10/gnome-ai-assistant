"""Weather via Open-Meteo (free, no API key)."""
import datetime
import json
import urllib.parse
import urllib.request

WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers",
       82: "violent showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def forecast(city):
    g = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(city))
    if not g.get("results"):
        return {"error": f"city not found: {city}"}
    p = g["results"][0]
    w = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto", "forecast_days": 5,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "hourly": "temperature_2m,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}))
    cur = w["current"]
    hours = w["hourly"]["time"]
    start = next((i for i, t in enumerate(hours) if t[:13] >= cur["time"][:13]), 0)
    return {
        "place": f"{p['name']}, {p.get('country', '')}",
        "current": {"temp_c": cur["temperature_2m"], "feels_like_c": cur["apparent_temperature"],
                    "humidity_pct": cur["relative_humidity_2m"], "wind_kmh": cur["wind_speed_10m"],
                    "condition": WMO.get(cur["weather_code"], "unknown")},
        "next_24h": [{"time": hours[i][11:16], "temp_c": w["hourly"]["temperature_2m"][i],
                      "rain_pct": w["hourly"]["precipitation_probability"][i]}
                     for i in range(start, min(start + 24, len(hours)))],
        "daily": [{"date": d, "min_c": w["daily"]["temperature_2m_min"][i], "max_c": w["daily"]["temperature_2m_max"][i],
                   "rain_pct": w["daily"]["precipitation_probability_max"][i],
                   "condition": WMO.get(w["daily"]["weather_code"][i], "unknown")}
                  for i, d in enumerate(w["daily"]["time"])],
    }


def widget_data(w):
    """Data for the `weather` widget from a forecast() result."""
    cur = w["current"]
    return {"place": w["place"], "condition": cur["condition"], "temp": cur["temp_c"], "feels_like": cur["feels_like_c"],
            "humidity": cur["humidity_pct"], "wind": cur["wind_kmh"], "unit": "°C",
            "hourly": [{"t": h["time"], "temp": h["temp_c"]} for h in w["next_24h"][::2]],
            "daily": [{"day": datetime.date.fromisoformat(d["date"]).strftime("%a"), "min": d["min_c"], "max": d["max_c"],
                       "condition": d["condition"], "rain": d["rain_pct"]} for d in w["daily"]]}
