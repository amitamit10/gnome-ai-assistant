"""LiveSTT against a local fake of the Gemini Live websocket protocol (no network, no key)."""
import base64
import json
import threading

import pytest

from aiassistant import stt


@pytest.fixture
def fake_live(monkeypatch, fake_key):
    from websockets.sync.server import serve
    received = {"setup": None, "audio": 0, "ended": False, "path": None}

    def handler(ws):
        received["path"] = ws.request.path
        received["setup"] = json.loads(ws.recv())
        ws.send(json.dumps({"setupComplete": {}}))
        for raw in ws:
            m = json.loads(raw)
            ri = m.get("realtimeInput", {})
            if "audio" in ri:
                assert ri["audio"]["mimeType"] == "audio/pcm;rate=16000"
                received["audio"] += len(base64.b64decode(ri["audio"]["data"]))
            if ri.get("audioStreamEnd"):
                received["ended"] = True
                for piece in ("What is the weather ", "in Jerusalem today?"):
                    ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": piece}}}))

    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(stt, "URL", f"ws://127.0.0.1:{server.socket.getsockname()[1]}/live")
    yield received
    server.shutdown()


def test_streams_audio_and_collects_the_transcript(fake_live):
    s = stt.LiveSTT()
    s.start()
    for _ in range(3):
        s.audio(base64.b64encode(b"\x00\x01" * 2048).decode())
    text = s.finish(settle=0.4, max_wait=5)
    assert text == "What is the weather in Jerusalem today?"
    assert fake_live["audio"] == 3 * 4096 and fake_live["ended"]
    assert fake_live["path"].endswith("key=test-key")
    assert fake_live["setup"]["setup"]["model"] == "models/gemini-3.5-transcribe-live"
    assert fake_live["setup"]["setup"]["inputAudioTranscription"] == {}


def test_missing_key_raises_cleanly():
    with pytest.raises(RuntimeError, match="no Gemini API key"):
        stt.LiveSTT().start()


def test_finish_with_no_speech_returns_empty(fake_live, monkeypatch):
    s = stt.LiveSTT()
    s.start()
    s.ws.send = lambda *_: None  # nothing reaches the server, so no transcript comes back
    assert s.finish(settle=0.2, max_wait=0.6) == ""
