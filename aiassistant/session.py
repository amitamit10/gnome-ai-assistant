"""The one conversation the chat window shows. Lives in the service so closing and reopening the window loses nothing.

`ask` runs in a worker thread and reports through callbacks, so the window never waits on a long blocking call (a window that
is closed mid-turn simply picks the reply up from `display` when it reopens).
"""
import threading

from .agent import Chat
from .llm import gemini


class Session:
    def __init__(self, chat=None):
        self.chat = chat or Chat()
        self.display = []          # what the window shows: {"role": "user", "text"} / {"role": "bot", **reply}
        self.status = ""           # progress line while a question is being answered ("" when idle)
        self.busy = False
        self.lock = threading.Lock()
        self.live = None           # active speech-to-text session (service.py owns the microphone)

    def snapshot(self):
        return {"items": self.display, "model": self.chat.model, "busy": self.busy, "status": self.status}

    def ask(self, text, on_status, on_reply):
        """Start answering `text` in a thread. Returns None, or an error string if a question is already running."""
        text = (text or "").strip()[:4000]
        if not text:
            return "empty question"
        if not self.lock.acquire(blocking=False):
            return "Still working on the previous question."
        self.busy = True
        self.status = "Thinking"
        self.display.append({"role": "user", "text": text})

        def set_status(s):
            self.status = s
            on_status(s)

        def work():
            try:
                try:
                    r = self.chat.ask(text, set_status)
                except gemini.GeminiError as e:
                    r = {"error": str(e)[:400]}
                except Exception as e:
                    r = {"error": (str(e)[:300] or type(e).__name__)}
                self.display.append({"role": "bot", **r})
            finally:
                self.busy = False
                self.status = ""
                self.lock.release()
            on_reply(r)

        threading.Thread(target=work, daemon=True, name="chat-turn").start()
        return None

    def reset(self):
        if self.busy:
            return False
        self.chat.reset()
        self.display.clear()
        return True
