"""Read-only device information for the assistant (wifi, battery, bluetooth, audio, disk...).

Safety model: every topic is a fixed function that reads files under /proc and /sys or runs a fixed, read-only
command (argv list, no shell, short timeout). Nothing takes free-form input from the model, nothing writes,
and MAC addresses / hardware serials are never returned.
"""
import datetime
import json
import os
import re
import subprocess
import time

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def _run(argv, timeout=5):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=ENV).stdout
    except Exception:
        return ""


def _read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def _nm_fields(line):
    """Split an `nmcli -t` line on unescaped colons."""
    return [f.replace("\\:", ":") for f in re.split(r"(?<!\\):", line)]


def wifi():
    rows = [_nm_fields(l) for l in _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY,CHAN,RATE", "dev", "wifi", "list"]).splitlines()]
    act = next((r for r in rows if r and r[0] == "yes" and len(r) >= 6), None)
    radio = _run(["nmcli", "radio", "wifi"]).strip()
    if not act:
        return {"wifi_radio": radio, "connected": False}
    return {"wifi_radio": radio, "connected": True, "ssid": act[1], "signal_pct": int(act[2] or 0),
            "security": act[3], "channel": act[4], "rate": act[5]}


def wifi_nearby():
    rows = [_nm_fields(l) for l in _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]).splitlines()]
    nets = sorted({(r[1], int(r[2] or 0), r[3]) for r in rows if len(r) >= 4 and r[1]}, key=lambda x: -x[1])[:8]
    return {"networks": [{"ssid": s, "signal_pct": q, "security": sec or "open"} for s, q, sec in nets], "count_seen": len(rows)}


def network():
    out = {"interfaces": []}
    try:
        for i in json.loads(_run(["ip", "-j", "addr"]) or "[]"):
            if i.get("operstate") == "UP" and i["ifname"] != "lo":
                out["interfaces"].append({"name": i["ifname"], "ipv4": [a["local"] for a in i.get("addr_info", []) if a["family"] == "inet"]})
        r = json.loads(_run(["ip", "-j", "route", "show", "default"]) or "[]")
        if r:
            out["default_gateway"], out["default_interface"] = r[0].get("gateway"), r[0].get("dev")
    except (ValueError, KeyError):
        pass
    return out


def battery():
    b = "/sys/class/power_supply/BAT0/"
    cap = _read(b + "capacity")
    if cap is None:
        return {"present": False}
    out = {"present": True, "percent": int(cap), "status": _read(b + "status"),
           "ac_connected": _read("/sys/class/power_supply/AC0/online") == "1"}
    try:
        now, full, power = (int(_read(b + k) or 0) for k in ("energy_now", "energy_full", "power_now"))
        if power > 0:
            hrs = ((full - now) if out["status"] == "Charging" else now) / power
            out["time_remaining_min"] = round(hrs * 60)
        design = int(_read(b + "energy_full_design") or 0)
        if design:
            out["health_pct"] = round(100 * full / design)
    except ValueError:
        pass
    return out


def memory():
    m = {k: int(v.split()[0]) * 1024 for k, v in (l.split(":", 1) for l in open("/proc/meminfo"))}
    gib = lambda n: round(n / 2**30, 1)
    return {"total_gb": gib(m["MemTotal"]), "available_gb": gib(m["MemAvailable"]), "used_pct": round(100 * (1 - m["MemAvailable"] / m["MemTotal"])),
            "swap_total_gb": gib(m["SwapTotal"]), "swap_used_gb": gib(m["SwapTotal"] - m["SwapFree"])}


def disk():
    out = []
    for path in ("/", os.path.expanduser("~")):
        s = os.statvfs(path)
        total, free = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
        out.append({"path": path, "total_gb": round(total / 2**30), "free_gb": round(free / 2**30), "used_pct": round(100 * (1 - free / total))})
        if path == os.path.expanduser("~") and out[0]["total_gb"] == out[-1]["total_gb"]:
            out.pop()  # same filesystem as /
    return {"filesystems": out}


def cpu():
    name = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "unknown")
    def sample():
        v = list(map(int, open("/proc/stat").readline().split()[1:]))
        return v[3] + v[4], sum(v)
    i0, t0 = sample(); time.sleep(0.25); i1, t1 = sample()
    return {"model": name, "threads": os.cpu_count(), "usage_pct": round(100 * (1 - (i1 - i0) / max(t1 - t0, 1))),
            "load_avg": [float(x) for x in open("/proc/loadavg").read().split()[:3]]}


def temperature():
    try:
        data = json.loads(_run(["sensors", "-j"]) or "{}")
    except ValueError:
        return {"error": "sensors unavailable"}
    out = {}
    for chip, vals in data.items():
        for label, sub in vals.items():
            if isinstance(sub, dict):
                for k, v in sub.items():
                    if k.endswith("_input") and k.startswith("temp"):
                        out[f"{chip}/{label}"] = round(v, 1)
    return {"celsius": dict(list(out.items())[:8])}


def uptime():
    s = float(open("/proc/uptime").read().split()[0])
    return {"up": f"{int(s // 86400)}d {int(s % 86400 // 3600)}h {int(s % 3600 // 60)}m", "since": (datetime.datetime.now() - datetime.timedelta(seconds=s)).strftime("%Y-%m-%d %H:%M")}


def system():
    osr = dict(l.strip().split("=", 1) for l in open("/etc/os-release") if "=" in l)
    return {"os": osr.get("PRETTY_NAME", "").strip('"'), "kernel": os.uname().release, "session": os.environ.get("XDG_SESSION_TYPE"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP"), "gnome_shell": _run(["gnome-shell", "--version"]).strip() or None}


def display():
    out = {}
    bl = "/sys/class/backlight/"
    if os.path.isdir(bl):
        for d in os.listdir(bl):
            cur, mx = _read(f"{bl}{d}/brightness"), _read(f"{bl}{d}/max_brightness")
            if cur and mx:
                out["brightness_pct"] = round(100 * int(cur) / int(mx))
                break
    gs = lambda schema, key: _run(["gsettings", "get", schema, key]).strip().strip("'")
    out["night_light"] = gs("org.gnome.settings-daemon.plugins.color", "night-light-enabled")
    out["text_scaling"] = gs("org.gnome.desktop.interface", "text-scaling-factor")
    out["color_scheme"] = gs("org.gnome.desktop.interface", "color-scheme")
    return out


def audio():
    def vol(target):
        m = re.search(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?", _run(["wpctl", "get-volume", target]))
        return {"volume_pct": round(float(m.group(1)) * 100), "muted": bool(m.group(2))} if m else None
    return {"output": vol("@DEFAULT_AUDIO_SINK@"), "microphone": vol("@DEFAULT_AUDIO_SOURCE@")}


def bluetooth():
    show = _run(["bluetoothctl", "show"])
    out = {"powered": bool(re.search(r"Powered:\s*yes", show))}
    out["connected_devices"] = [l.split(" ", 2)[2] for l in _run(["bluetoothctl", "devices", "Connected"]).splitlines() if l.startswith("Device ")]  # names only
    return out


def time_info():
    now = datetime.datetime.now().astimezone()
    return {"local_time": now.strftime("%Y-%m-%d %H:%M:%S"), "weekday": now.strftime("%A"), "timezone": str(now.tzinfo), "utc_offset": now.strftime("%z")}


def location():
    """Approximate only: timezone and locale. (No GPS/GeoClue; IP-based lookup is deliberately not used.)"""
    tz = _run(["timedatectl", "show", "-p", "Timezone", "--value"]).strip() or "unknown"
    return {"timezone": tz, "city_guess_from_timezone": tz.split("/")[-1].replace("_", " "), "locale": os.environ.get("LANG"),
            "note": "approximate: derived from the system timezone, not from GPS or the network"}


def processes():
    rows = _run(["ps", "-eo", "comm,pcpu,pmem", "--sort=-pcpu"]).splitlines()[1:]  # command names only, never full command lines
    rows = [r for r in rows if r.split()[0] not in ("ps", "systemd-timedat", "sensors", "nmcli", "upower")]
    return {"top_by_cpu": [dict(zip(("name", "cpu_pct", "mem_pct"), r.rsplit(None, 2))) for r in rows[:5]]}


TOPICS = {"wifi": wifi, "wifi_nearby": wifi_nearby, "network": network, "battery": battery, "memory": memory, "disk": disk,
          "cpu": cpu, "temperature": temperature, "uptime": uptime, "system": system, "display": display, "audio": audio,
          "bluetooth": bluetooth, "time": time_info, "location": location, "processes": processes}


def get(topic):
    """Read-only info for one topic, or all of them with topic='summary'."""
    if topic == "summary":
        return {t: TOPICS[t]() for t in ("system", "battery", "wifi", "memory", "disk", "cpu", "uptime", "time")}
    fn = TOPICS.get(topic)
    if not fn:
        return {"error": f"unknown topic '{topic}'. Topics: summary, {', '.join(TOPICS)}"}
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}
