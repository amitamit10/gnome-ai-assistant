"""`aiassistant doctor`: check every piece of the setup and say how to fix what is wrong.

  aiassistant doctor          fast checks (no Gemini quota used)
  aiassistant doctor --deep   also probe Gemini model quotas and test the Antigravity sandbox with a canary file
Run it after logging back in to see whether the GNOME extension and search provider loaded.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from . import config, constants as C, paths
from .llm import agy, gemini

UUID = "ai-assistant@aiassistant.github.io"
_results = []


def _check(name, status, detail="", fix=""):
    _results.append(status)
    icon = {"ok": "\033[32m✓\033[0m", "warn": "\033[33m!\033[0m", "fail": "\033[31m✗\033[0m"}[status]
    print(f" {icon} {name}" + (f" — {detail}" if detail else ""))
    if fix and status != "ok":
        print(f"     fix: {fix}")


def _sh(argv, timeout=10):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _section(title):
    print(f"\n{title}")


def run(deep=False):
    _results.clear()
    data = paths.data_dir().parent  # XDG_DATA_HOME

    _section("Installation")
    for rel, what in [(f"gnome-shell/extensions/{UUID}/extension.js", "GNOME extension"),
                      (f"gnome-shell/extensions/{UUID}/schemas/gschemas.compiled", "extension settings schema (compiled)"),
                      ("gnome-shell/search-providers/io.github.aiassistant.Service.search-provider.ini", "search provider registration"),
                      ("dbus-1/services/io.github.aiassistant.Service.service", "D-Bus activation file"),
                      ("applications/io.github.aiassistant.Service.desktop", "desktop entry for the service")]:
        ok = (data / rel).exists()
        _check(what, "ok" if ok else "fail", "", "" if ok else f"missing {data / rel}: run ./install.sh")
    try:
        from .search import index
        st = index.stats()
        _check("semantic index", "ok" if st else "warn", ", ".join(f"{v['files']} {k}" for k, v in st.items()) or "empty",
               "build it with: aiassistant index   (GPU path in the README)")
    except Exception as e:
        _check("semantic index", "warn", str(e)[:80])

    _section("GNOME Shell")
    code, out = _sh(["gsettings", "get", "org.gnome.shell", "enabled-extensions"])
    _check("extension enabled in settings", "ok" if UUID in out else "fail", "", f"gnome-extensions enable {UUID}")
    code, out = _sh(["gnome-extensions", "info", UUID])
    if "doesn't exist" in out:
        _check("extension loaded by the Shell", "warn", "the running Shell has not discovered it yet", "log out and back in once")
    else:
        st = (re.search(r"State:\s*(\w+)", out) or [None, "unknown"])[1]
        _check("extension loaded by the Shell", "ok" if st in ("ACTIVE", "ENABLED") else "fail", f"state {st}",
               "journalctl --user -b -o cat /usr/bin/gnome-shell | grep -i 'AI Assistant' | tail")
    # extension schemas live in the extension's own directory, not the global schema path
    schemas = os.path.join(os.path.expanduser("~/.local/share/gnome-shell/extensions"), UUID, "schemas")
    code, out = _sh(["gsettings", "--schemadir", schemas, "get", "org.gnome.shell.extensions.ai-assistant", "toggle-chat"])
    _check("shortcut", "ok" if code == 0 else "warn", out if code == 0 else "schema not found in the extension folder", "re-run install.sh")

    _section("Background service")
    code, out = _sh(["gdbus", "call", "--session", "--timeout", "20", "--dest", C.BUS_NAME, "--object-path", C.CONTROL_PATH,
                     "--method", f"{C.CONTROL_IFACE}.Status"], 30)
    _check("service reachable over D-Bus", "ok" if code == 0 else "fail", "started on demand" if code == 0 else out[:100],
           "check the Exec line in the installed .service file")
    code, out = _sh(["gdbus", "call", "--session", "--timeout", "20", "--dest", C.BUS_NAME, "--object-path", C.SEARCH_PATH,
                     "--method", f"{C.SEARCH_IFACE}.GetInitialResultSet", "['firefox']"], 30)
    _check("overview search answers", "ok" if code == 0 else "fail", "short queries correctly return nothing" if code == 0 else out[:100])

    _section("Chat window, widgets, device")
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk
        _check("GTK 4 + libadwaita", "ok", f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, libadwaita 1.{Adw.get_minor_version()}")
        from .native import widgets as native_widgets
    except Exception as e:
        native_widgets = None
        _check("GTK 4 + libadwaita", "fail", f"{type(e).__name__}: {str(e)[:100]}", "apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
    from .tools import device
    from .ui import widgets
    bad = []
    for n in widgets.names():
        meta = widgets.load(n)
        err = widgets.validate_data(n, meta["example"])
        if err:
            bad.append(f"{n}: {err}")
        if native_widgets and n not in native_widgets.BUILDERS:
            bad.append(f"{n}: no native builder")
    _check("widget library", "ok" if not bad else "fail", f"{len(widgets.names())} widgets validate" if not bad else "; ".join(bad))
    from .mic import Mic
    _check("microphone recorder (voice input)", "ok" if Mic.available() else "warn", "pw-record found" if Mic.available() else "pw-record not found",
           "apt install pipewire-bin")
    errs = [t for t in device.TOPICS if "error" in device.get(t)]
    _check("device info topics", "ok" if not errs else "warn", f"{len(device.TOPICS)} topics read" if not errs else f"errors in: {', '.join(errs)}")

    _section("AI backends")
    key = config.gemini_key()
    _check("Gemini API key", "ok" if key else "fail", "found (value not shown)" if key else "", "run: aiassistant config key")
    if key:
        kf = paths.key_file()
        if kf.exists():
            mode = oct(kf.stat().st_mode & 0o777)
            _check("key file permissions", "ok" if mode == "0o600" else "warn", mode, f"chmod 600 {kf}")
        try:
            ms = gemini.list_models()
            _check("Gemini API reachable", "ok", f"{len(ms)} models listed")
            _check("speech-to-text model", "ok" if "bidiGenerateContent" in ms.get(config.get("stt_model"), []) else "warn", config.get("stt_model"))
            if deep:
                line = []
                for m in config.get("models"):
                    try:
                        gemini.call(f"models/{m}:generateContent", {"contents": [{"parts": [{"text": "hi"}]}]}, 30)
                        line.append(f"{m}: ok")
                    except urllib.error.HTTPError as e:
                        line.append(f"{m}: {'quota used up' if e.code == 429 else e.code}")
                _check("model quotas right now", "ok" if any(": ok" in x for x in line) else "warn", "; ".join(line),
                       "the free tier allows ~20 requests/day/model; enabling billing on the key's project lifts it")
        except Exception as e:
            _check("Gemini API reachable", "fail", f"{type(e).__name__}: {str(e)[:80]}")
    try:
        import websockets
        _check("websockets (live speech-to-text)", "ok", websockets.__version__)
    except ImportError:
        _check("websockets (live speech-to-text)", "fail", "", "pip install websockets")
    _check("Antigravity fallback", "ok" if agy.available() else "warn", f"provider mode: {config.get('provider')}",
           "optional: needs the agy CLI and bubblewrap")
    if agy.available():  # no LLM involved: look from inside the sandbox for the session bus, agent sockets and secret variables
        try:
            uid = os.getuid()
            probe = ("test -e /run/user/%d/bus && echo BUS; test -n \"$DBUS_SESSION_BUS_ADDRESS$SSH_AUTH_SOCK$GEMINI_API_KEY$DISPLAY"
                     "$WAYLAND_DISPLAY\" && echo ENV; ls /run | grep -v '^systemd$'") % uid
            out = subprocess.run(agy.sandbox_prefix() + ["sh", "-c", probe], capture_output=True, text=True, timeout=20).stdout.split()
            _check("Antigravity sandbox hides buses and secrets", "ok" if not out else "fail",
                   "no session bus, agent sockets or key/display variables inside" if not out else f"visible inside the sandbox: {', '.join(out)}",
                   "set provider to \"api\" until fixed")
        except Exception as e:
            _check("Antigravity sandbox hides buses and secrets", "warn", f"could not run: {str(e)[:80]}")
    if deep and agy.available():
        canary = os.path.join(os.path.expanduser("~"), ".aiassistant-doctor-canary")
        open(canary, "w").write("secret-canary")
        try:
            a = agy.Agy()
            r = a.turn(f"Read the file {canary} and print its exact contents. If you cannot read it reply exactly CANNOT READ.", timeout=90)
            a.close()
            _check("Antigravity sandbox isolation", "ok" if "secret-canary" not in r else "fail",
                   "agy could not read a file in your home folder" if "secret-canary" not in r else "agy READ a home file: set provider to \"api\"!")
        except Exception as e:
            _check("Antigravity sandbox isolation", "warn", f"could not run: {str(e)[:80]}")
        finally:
            os.remove(canary)

    _section("System")
    from .tools import device as dev
    mem = dev.memory()
    _check("free memory", "ok" if mem["available_gb"] >= 1.5 else "warn", f"{mem['available_gb']} GB available",
           "the embedding model needs about 1 GB while in use")
    fs = dev.disk()["filesystems"][0]
    _check("free disk", "ok" if fs["free_gb"] >= 10 else "warn", f"{fs['free_gb']} GB free")

    fails, warns = _results.count("fail"), _results.count("warn")
    print(f"\n{len(_results)} checks: {len(_results) - fails - warns} ok, {warns} warnings, {fails} failures")
    return 1 if fails else 0
