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
    for flag in ("--clearenv", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent"):
        assert flag in argv
    r = subprocess.run(argv + ["sh", "-c", f"env; ls -A /run; test -e /run/user/{os.getuid()}/bus && echo BUS; true"],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert "leak-me" not in r.stdout and "DBUS_" not in r.stdout and "SSH_AUTH_SOCK" not in r.stdout and "BUS\n" not in r.stdout
    assert [x for x in r.stdout.split() if x == "user"] == [], "/run/user must not exist inside the sandbox"


def test_home_is_hidden_except_the_scratch_dir():
    r = subprocess.run(agy.sandbox_prefix() + ["sh", "-c", "ls -A ~ | head"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and ".ssh" not in r.stdout and "Documents" not in r.stdout
