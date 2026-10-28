"""Integration: install into a sandbox, run the real D-Bus service, call it like GNOME Shell and the extension do.

Uses the real session bus (under the unique name io.github.aiassistant.Service). Skipped when no session bus is available.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUS = f"io.github.aiassistant.Test{os.getpid()}"   # never the real name: a live installation must not be touched
UUID = "ai-assistant@aiassistant.github.io"

pytestmark = pytest.mark.skipif(not os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not shutil.which("gdbus"),
                                reason="needs a D-Bus session bus and gdbus")


def gdbus(path, method, *args, timeout=40):
    return subprocess.run(["gdbus", "call", "--session", "--timeout", str(timeout), "--dest", BUS, "--object-path", path,
                           "--method", method, *args], capture_output=True, text=True)


@pytest.fixture
def installed(sandbox):
    env = os.environ.copy()
    r = subprocess.run([str(ROOT / "install.sh"), "--dev", "--no-venv", "--no-enable", "--python", sys.executable],
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return sandbox, r.stdout


@pytest.fixture
def service(installed):
    sandbox, _ = installed
    recorder = sandbox / "fake-window.sh"   # stands in for the GTK window so no real window opens during tests
    recorder.write_text(f'#!/bin/sh\necho "$@" >> {sandbox}/window-args.txt\n')
    recorder.chmod(0o755)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "AIASSISTANT_BUS_NAME": BUS, "AIASSISTANT_WINDOW_CMD": f"{recorder} window"}
    p = subprocess.Popen([sys.executable, "-m", "aiassistant", "service"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Status", timeout=3).returncode == 0:
            break
        time.sleep(0.2)
    else:
        p.kill()
        pytest.fail("service did not appear on the bus: " + p.stderr.read())
    yield p
    gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Quit")
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def test_installer_places_every_file(installed):
    sandbox, out = installed
    data = sandbox / "data"
    ext = data / "gnome-shell" / "extensions" / UUID
    assert (ext / "extension.js").exists() and (ext / "metadata.json").exists() and (ext / "prefs.js").exists()
    assert (ext / "schemas" / "gschemas.compiled").exists(), "schemas must be compiled at install time"
    svc = (data / "dbus-1" / "services" / "io.github.aiassistant.Service.service").read_text()
    assert "Name=io.github.aiassistant.Service" in svc and "-m aiassistant service" in svc and "@EXEC@" not in svc
    desktop_file = data / "applications" / "io.github.aiassistant.Service.desktop"
    desktop = desktop_file.read_text()
    assert "@EXEC@" not in desktop and "@CHAT@" not in desktop and " chat" in desktop
    # GNOME Shell ignores a search provider whose application should_show() is false (NoDisplay/Hidden):
    assert not re.search(r"^\s*(NoDisplay|Hidden)\s*=\s*true", desktop, re.M | re.I), "NoDisplay/Hidden hides the search provider"
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    info = Gio.DesktopAppInfo.new_from_filename(str(desktop_file))
    assert info is not None and info.should_show(), "the Shell would skip the search provider (should_show() is False)"
    ini = (data / "gnome-shell" / "search-providers" / "io.github.aiassistant.Service.search-provider.ini").read_text()
    assert "BusName=io.github.aiassistant.Service" in ini and "ObjectPath=/io/github/aiassistant/Search" in ini
    chat = (data / "applications" / "io.github.aiassistant.Chat.desktop").read_text()
    assert "@WINDOW@" not in chat and " window" in chat and "NoDisplay=true" in chat   # the window's own entry is hidden; the Service one is visible
    launcher = sandbox / "home" / ".local" / "bin" / "aiassistant"
    assert launcher.exists() and os.access(launcher, os.X_OK)
    assert "Next steps" in out and "aiassistant config key" in out
    # nothing outside the sandbox was touched
    assert str(Path.home()) == str(sandbox / "home")


def test_installed_launcher_runs(installed):
    sandbox, _ = installed
    r = subprocess.run([str(sandbox / "home" / ".local" / "bin" / "aiassistant"), "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and "0.1.0" in r.stdout


def test_service_answers_the_search_provider_interface(service):
    iface = "org.gnome.Shell.SearchProvider2"
    p = "/io/github/aiassistant/Search"
    r = gdbus(p, f"{iface}.GetInitialResultSet", "['firefox']")
    assert r.returncode == 0 and "[]" in r.stdout          # short app-name queries are ignored
    r = gdbus(p, f"{iface}.GetResultMetas", "['image|/tmp/a.png|', 'text|/tmp/n.md|hello world']")
    assert r.returncode == 0 and "a.png" in r.stdout and "text-x-generic" in r.stdout
    assert gdbus(p, f"{iface}.LaunchSearch", "['x']", "0").returncode == 0


def test_open_launches_the_native_window_once(service, sandbox):
    r = gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Open")
    assert r.returncode == 0, r.stderr
    args_file = sandbox / "window-args.txt"
    for _ in range(50):
        if args_file.exists():
            break
        time.sleep(0.1)
    assert args_file.read_text().strip() == "window"
    # a double press while the window starts must not launch a second one
    gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Open")
    time.sleep(0.5)
    assert len(args_file.read_text().strip().splitlines()) == 1


def test_chat_api_over_dbus(service):
    ctl, iface = "/io/github/aiassistant/Control", "io.github.aiassistant.Control"
    hist = gdbus(ctl, f"{iface}.History")
    assert hist.returncode == 0 and '"items": []' in hist.stdout and '"busy": false' in hist.stdout
    assert "empty question" in gdbus(ctl, f"{iface}.Ask", "''").stdout        # never reaches an LLM
    assert "true" in gdbus(ctl, f"{iface}.Reset").stdout
    assert "false" in gdbus(ctl, f"{iface}.OpenFile", "'/etc/passwd'").stdout   # only indexed files may be opened


def test_service_survives_garbage_and_quits_on_request(service):
    assert gdbus("/io/github/aiassistant/Search", "org.gnome.Shell.SearchProvider2.GetResultMetas", "['no-pipes-here']").returncode != 0
    # the bad call must not kill it
    assert gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Status").returncode == 0
    assert gdbus("/io/github/aiassistant/Control", "io.github.aiassistant.Control.Quit").returncode == 0
    service.wait(timeout=10)
    assert service.returncode == 0


def test_uninstall_removes_everything_but_keeps_data(installed):
    sandbox, _ = installed
    data = sandbox / "data"
    (data / "gnome-ai-assistant").mkdir(parents=True, exist_ok=True)
    (data / "gnome-ai-assistant" / "index.db").write_text("keep me")
    env = {**os.environ}
    r = subprocess.run([str(ROOT / "uninstall.sh")], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert not (data / "gnome-shell" / "extensions" / UUID).exists()
    assert not (data / "dbus-1" / "services" / "io.github.aiassistant.Service.service").exists()
    assert not (sandbox / "home" / ".local" / "bin" / "aiassistant").exists()
    assert (data / "gnome-ai-assistant" / "index.db").read_text() == "keep me"
    subprocess.run([str(ROOT / "uninstall.sh"), "--purge"], capture_output=True, env=env, timeout=60)
    assert not (data / "gnome-ai-assistant").exists()
