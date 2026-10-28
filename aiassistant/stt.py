"""Streaming speech-to-text through the Gemini Live API (dedicated transcription model).

The chat page captures the microphone and posts 16 kHz mono PCM chunks to the local server; this module relays them
over one WebSocket and accumulates the transcript. The live transcription model delivers text after the speaker
stops (about 1-2 s), not word by word. Audio is sent to Google; see PRIVACY.md.
"""
import json
import threading
import time

from . import config

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
MAX_SECONDS = 180


class LiveSTT:
    def __init__(self):
        self.ws = None
        self.text = ""
        self.error = None
        self.last_rx = time.time()
        self.started = 0.0
        self._send_lock = threading.Lock()
        self._closed = threading.Event()

    def start(self):
        from websockets.sync.client import connect
        key = config.gemini_key()
        if not key:
            raise RuntimeError("no Gemini API key configured")
        self.ws = connect(URL + "?key=" + key, max_size=None, open_timeout=15)
        self.ws.send(json.dumps({"setup": {"model": f"models/{config.get('stt_model')}",
                                           "generationConfig": {"responseModalities": ["TEXT"]},
                                           "inputAudioTranscription": {}}}))
        reply = json.loads(self.ws.recv(timeout=15))
        if "setupComplete" not in reply:
            raise RuntimeError("live session refused: " + str(reply)[:150])
        self.started = time.time()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            while not self._closed.is_set():
                try:
                    m = json.loads(self.ws.recv(timeout=1))
                except TimeoutError:
                    if time.time() - self.started > MAX_SECONDS:
                        break
                    continue
                t = m.get("serverContent", {}).get("inputTranscription", {}).get("text")
                if t:
                    self.text += t
                    self.last_rx = time.time()
        except Exception as e:  # connection closed by the server or network error
            if not self._closed.is_set():
                self.error = f"{type(e).__name__}: {str(e)[:80]}"
        finally:
            self._closed.set()

    def audio(self, b64_pcm16):
        with self._send_lock:
            self.ws.send(json.dumps({"realtimeInput": {"audio": {"data": b64_pcm16, "mimeType": "audio/pcm;rate=16000"}}}))

    def finish(self, settle=1.0, max_wait=8.0):
        """Signal end of audio, wait until transcript text stops arriving, close, return the text."""
        try:
            with self._send_lock:
                self.ws.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
            t0 = time.time()
            while time.time() - t0 < max_wait and not self._closed.is_set():
                if self.text and time.time() - self.last_rx > settle:
                    break
                time.sleep(0.1)
        except Exception:
            pass
        self.close()
        return self.text.strip()

    def close(self):
        self._closed.set()
        try:
            self.ws.close()
        except Exception:
            pass
