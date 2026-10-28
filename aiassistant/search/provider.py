"""GNOME Shell overview search: the logic behind the org.gnome.Shell.SearchProvider2 interface (no D-Bus in here).

Answers only for deliberate queries, because semantic scores are not calibrated and answering every keystroke would
flood normal app searches with junk:
  * `? words` or `ai words`      semantic search (1+ words after the trigger)
  * 3 or more words              semantic search automatically (e.g. "screenshots of the settings menu")
  * `ask a question`             answer from your notes (needs a Gemini key), shown above the source files
Short queries (an app name like "firefox") return nothing.
"""
import os
import threading
import time

from .. import config
from ..tools import files
from . import ask, query

TRIGGERS = ("?", "ai")
AUTO_MIN_WORDS = 3


def parse(terms):
    """(mode, query) with mode in {'search', 'ask', 'warm', None}."""
    if not terms:
        return None, ""
    first = terms[0].lower()
    if first == "ask" and len(terms) > 1:
        q = " ".join(terms[1:]).strip()
        return ("ask", q) if len(q) >= 8 else (None, "")
    if first in TRIGGERS:
        q = " ".join(terms[1:]).strip()
        return ("search", q) if len(q) >= 2 else ("warm", "")  # just typed the trigger: preload the model
    if len(terms) >= AUTO_MIN_WORDS:
        return "search", " ".join(terms)
    return None, ""


def meta_for(ident):
    kind, path, label = ident.split("|", 2)
    short = files.short(path)
    if kind == "answer":
        return {"id": ident, "name": "Answer: " + " ".join(label.split())[:140], "description": f"from {short}", "gicon": "dialog-information"}
    if kind == "image":
        return {"id": ident, "name": os.path.basename(path), "description": short, "gicon": path}
    if kind == "video":
        return {"id": ident, "name": os.path.basename(path), "description": f"{short} @{label}", "gicon": "video-x-generic"}
    return {"id": ident, "name": os.path.basename(path), "description": f"{short} - {' '.join(label.split())[:90]}",
            "gicon": "text-x-generic"}


class Provider:
    """Thread-safe request handling: newer keystrokes supersede older searches."""

    def __init__(self):
        self.latest = 0
        self.counter = 0
        self.lock = threading.Lock()

    def results(self, terms):
        """Result ids for the terms; may block (model load, network) so call from a worker thread."""
        mode, q = parse(terms)
        if mode is None:
            return []
        if mode == "warm":
            threading.Thread(target=lambda: query.shared().warm(), daemon=True).start()
            return []
        with self.lock:
            self.counter += 1
            ticket = self.latest = self.counter
        if config.gemini_key():  # debounce: do not call the API on every keystroke
            time.sleep(1.0 if mode == "ask" else 0.5)
            if ticket != self.latest:
                return []
        try:
            if mode == "ask":
                got = ask.answer(q)
                if not got:
                    return []
                text, srcs = got
                return [f"answer|{srcs[0]}|{text}"] + [f"text|{p}|" for p in srcs[:4]]
            hits = query.shared().search(q, is_current=lambda: ticket == self.latest)
        except FileNotFoundError:
            return []
        return [f"{h['kind']}|{h['path']}|{h['label']}" for h in hits]

    def activate(self, ident):
        files.open_file(ident.split("|", 2)[1])
