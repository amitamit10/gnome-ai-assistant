import http.client
import pytest
from aiassistant.llm import gemini


def test_retries_a_dropped_connection(monkeypatch):
    calls = []

    def fake(path, body=None, timeout=60):
        calls.append(path)
        if len(calls) == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return {"ok": True}
    monkeypatch.setattr(gemini, "call", fake)
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini, "models", lambda: ["m1"])
    assert gemini.generate([{"role": "user", "parts": [{"text": "hi"}]}]) == ("m1", {"ok": True})
    assert len(calls) == 2


def test_persistent_network_failure_is_a_friendly_error(monkeypatch):
    def fake(path, body=None, timeout=60):
        raise ConnectionResetError("boom")
    monkeypatch.setattr(gemini, "call", fake)
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini, "models", lambda: ["m1"])
    with pytest.raises(gemini.GeminiError, match="Can't reach Gemini"):
        gemini.generate([{"role": "user", "parts": [{"text": "hi"}]}])


def test_failed_model_is_tried_last_next_time(monkeypatch):
    import urllib.error
    gemini._cooldown.clear()
    seen = []

    def fake(path, body=None, timeout=60):
        m = path.split("/")[1].split(":")[0]
        seen.append(m)
        if m == "m1":
            raise urllib.error.HTTPError("u", 503, "busy", {}, None)
        return {"ok": True}
    monkeypatch.setattr(gemini, "call", fake)
    monkeypatch.setattr(gemini, "models", lambda: ["m1", "m2"])
    assert gemini.generate([])[0] == "m2"
    seen.clear()
    assert gemini.generate([])[0] == "m2"
    assert seen == ["m2"]   # m1 was not tried again
    gemini._cooldown.clear()


def test_timeout_moves_on_without_retrying_and_400_retries_without_thinking(monkeypatch):
    import urllib.error
    gemini._cooldown.clear()
    seen = []

    def fake(path, body=None, timeout=60):
        m = path.split("/")[1].split(":")[0]
        seen.append((m, "thinkingConfig" in body["generationConfig"]))
        if m == "slow":
            raise TimeoutError("timed out")
        if m == "old" and "thinkingConfig" in body["generationConfig"]:
            raise urllib.error.HTTPError("u", 400, "bad", {}, None)
        return {"ok": True}
    monkeypatch.setattr(gemini, "call", fake)
    monkeypatch.setattr(gemini, "models", lambda: ["slow", "old"])
    assert gemini.generate([])[0] == "old"
    assert seen == [("slow", True), ("old", True), ("old", False)]   # one attempt for the stalled model, then the fallback
    gemini._cooldown.clear()


def test_a_slow_model_is_backed_up_by_the_next_and_the_first_answer_wins(monkeypatch):
    import threading
    gemini._cooldown.clear()
    release = threading.Event()

    def fake(path, body=None, timeout=60):
        m = path.split("/")[1].split(":")[0]
        if m == "slow":
            release.wait(5)
            return {"from": "slow"}
        return {"from": m}
    monkeypatch.setattr(gemini, "call", fake)
    monkeypatch.setattr(gemini, "HEDGE", 0.2)
    monkeypatch.setattr(gemini, "models", lambda: ["slow", "fast"])
    import time
    t = time.monotonic()
    assert gemini.generate([])[0] == "fast" and time.monotonic() - t < 2
    release.set()
    gemini._cooldown.clear()
