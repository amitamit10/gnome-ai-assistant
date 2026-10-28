"""Microphone capture for voice input: `pw-record` (PipeWire) streams 16 kHz mono PCM into a Gemini Live transcription session.

Only runs between SttStart and SttStop, i.e. while the user holds the microphone button on. Audio is sent to Google; see PRIVACY.md.
"""
import base64
import shutil
import subprocess
import threading

from . import stt

CHUNK = 6400  # 0.2 s of 16 kHz s16 mono


class Mic:
    def __init__(self):
        self.live = stt.LiveSTT()
        self.proc = None
        self._thread = None

    @staticmethod
    def available():
        return shutil.which("pw-record") is not None

    def start(self):
        if not self.available():
            raise RuntimeError("pw-record (pipewire-bin) is not installed")
        self.live.start()
        self.proc = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "-"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._pump, daemon=True, name="mic")
        self._thread.start()

    def _pump(self):
        try:
            while True:
                data = self.proc.stdout.read(CHUNK)
                if not data:
                    break
                self.live.audio(base64.b64encode(data).decode())
        except Exception:
            pass  # the recorder was stopped or the socket closed

    def error(self):
        return self.live.error

    def stop(self):
        """Stop recording and return the transcript (may take 1-2 s while the last words are transcribed)."""
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._thread:
            self._thread.join(1)
        return self.live.finish()

    def cancel(self):
        if self.proc:
            self.proc.kill()
        self.live.close()
