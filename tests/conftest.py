"""Shared fixtures: every test runs with XDG directories redirected to a temp folder and no network access."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
        d = tmp_path / sub
        d.mkdir()
        os.chmod(d, 0o700)
        monkeypatch.setenv(var, str(d))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    def no_network(*a, **k):
        raise AssertionError("a test tried to use the network")
    from aiassistant.llm import gemini
    monkeypatch.setattr(gemini, "call", no_network)
    gemini._cooldown.clear()
    gemini._no_thinking.clear()
    return tmp_path


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
