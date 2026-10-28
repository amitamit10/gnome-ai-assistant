import os
import shutil
import subprocess
from pathlib import Path

import pytest

from aiassistant import paths
from aiassistant.llm import agy

pytestmark = pytest.mark.skipif(not agy.available(), reason="needs bubblewrap and the agy CLI")


@pytest.fixture(autouse=True)
def workdir_in_the_real_home(monkeypatch):
    """The scratch dir must live under $HOME like in real use: the sandbox hides /tmp, where the test sandbox would put it."""
    d = Path(agy.HOME) / ".cache" / f"aiassistant-sandbox-test-{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "agy_workdir", lambda: d)
    yield
    shutil.rmtree(d, ignore_errors=True)


def test_the_sandbox_hides_buses_and_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "leak-me")
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "leak-me-too")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1/bus")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1/keyring/ssh")
    argv = agy.sandbox_prefix()
    for flag in ("--clearenv", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--new-session", "--die-with-parent"):
        assert flag in argv
    r = subprocess.run(argv + ["sh", "-c", f"env; ls -A /run; test -e /run/user/{os.getuid()}/bus && echo BUS; true"],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert "leak-me" not in r.stdout and "DBUS_" not in r.stdout and "SSH_AUTH_SOCK" not in r.stdout and "BUS\n" not in r.stdout
    assert [x for x in r.stdout.split() if x == "user"] == [], "/run/user must not exist inside the sandbox"


def test_home_is_hidden_except_the_scratch_dir():
    r = subprocess.run(agy.sandbox_prefix() + ["sh", "-c", "ls -A ~ | head"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and ".ssh" not in r.stdout and "Documents" not in r.stdout


def test_dev_is_minimal_so_no_host_devices_leak_in():
    r = subprocess.run(agy.sandbox_prefix() + ["sh", "-c", "ls /dev"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and "null" in r.stdout and "urandom" in r.stdout
    assert "sda" not in r.stdout and "nvme0n1" not in r.stdout and "video0" not in r.stdout and "dri" not in r.stdout


@pytest.mark.skipif(not os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not shutil.which("xdg-dbus-proxy") or not shutil.which("gdbus"),
                    reason="needs a session bus, xdg-dbus-proxy and gdbus")
def test_the_bus_inside_the_sandbox_is_filtered_to_the_keyring_only():
    proc, sock = agy.start_bus_proxy()
    assert proc and sock
    try:
        r = subprocess.run(agy.sandbox_prefix(sock) + ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
                                                       "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.ListNames"],
                           capture_output=True, text=True, timeout=20)
        names = r.stdout
        assert "org.gnome.Shell" not in names and "io.github.aiassistant" not in names, names
        r2 = subprocess.run(agy.sandbox_prefix(sock) + ["gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path",
                                                        "/org/gnome/Shell", "--method", "org.gnome.Shell.Eval", "1"],
                            capture_output=True, text=True, timeout=20)
        assert r2.returncode != 0, "GNOME Shell must not be reachable from the sandbox"
    finally:
        proc.kill()
        os.path.exists(sock) and os.remove(sock)


def test_keyring_access_is_off_by_default(monkeypatch):
    started = []
    monkeypatch.setattr(agy, "start_bus_proxy", lambda: started.append(1) or (None, None))
    a = agy.Agy()
    a._spawn = agy.Agy._spawn.__get__(a)
    class FakeProc:
        stdin = type("S", (), {"close": lambda s: None})()
        poll = lambda s: None
        terminate = wait = kill = lambda s, *a, **k: None
    monkeypatch.setattr(agy.subprocess, "Popen", lambda *x, **k: FakeProc())
    a._spawn()
    assert started == [] and a.bus_sock is None and "DBUS_SESSION_BUS_ADDRESS" not in a._argv()
    from aiassistant import config
    config.save({"agy_keyring": True})
    a._spawn()
    assert started == [1]
