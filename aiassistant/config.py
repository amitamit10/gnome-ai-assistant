"""User configuration (JSON) and the Gemini API key. Both optional; sensible defaults for everything."""
import json
import os
from pathlib import Path

from . import paths

DEFAULTS = {
    # how the assistant picks an LLM: "auto" = Gemini API first, then Antigravity when the API is out of quota;
    # "api" = never use Antigravity; "agy" = Antigravity only
    "provider": "auto",
    # Gemini models tried in order (free tier = about 20 requests/day per model, so a long list stretches the budget)
    "models": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
               "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"],
    "agy_model": "gemini-3.8-flash-low",
    "agy_keyring": False,  # opt-in: let the sandboxed agy reach the desktop keyring (Secret Service) through a filtered bus
    "stt_model": "gemini-3.5-transcribe-live",
    # semantic search: folders to index, and which embedding model (must match the index; see `aiassistant index`)
    "index_roots": ["~/Documents", "~/Downloads", "~/Desktop", "~/Pictures", "~/Videos"],
    "embed_model": "google/embeddinggemma-2",
    # chat window
}


def load():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(paths.config_file().read_text()))
    except (OSError, ValueError):
        pass
    return cfg


def get(key):
    return load()[key]


def save(updates):
    cfg = {}
    try:
        cfg = json.loads(paths.config_file().read_text())
    except (OSError, ValueError):
        pass
    cfg.update(updates)
    paths.ensure(paths.config_dir(), 0o700)
    paths.config_file().write_text(json.dumps(cfg, indent=2))


def gemini_key():
    """API key from the environment or ~/.config/gnome-ai-assistant/gemini_key (never logged or printed)."""
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k.strip()
    try:
        return Path(paths.key_file()).read_text().strip() or None
    except OSError:
        return None


def expand_roots(cfg=None):
    return [os.path.expanduser(r) for r in (cfg or load())["index_roots"]]
