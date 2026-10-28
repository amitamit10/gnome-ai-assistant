"""All filesystem locations, derived from XDG variables so nothing is hard-coded to one user or machine.

Tests (and sandboxed installs) redirect everything by setting XDG_CONFIG_HOME / XDG_DATA_HOME / XDG_CACHE_HOME /
XDG_RUNTIME_DIR.
"""
import os
from pathlib import Path

APP = "gnome-ai-assistant"
PACKAGE_DIR = Path(__file__).resolve().parent
BUNDLED = PACKAGE_DIR / "data"  # shipped with the package: widget descriptions, D-Bus templates


def _xdg(var, default):
    return Path(os.environ.get(var) or os.path.expanduser(default))


def config_dir():
    return _xdg("XDG_CONFIG_HOME", "~/.config") / APP


def data_dir():
    return _xdg("XDG_DATA_HOME", "~/.local/share") / APP


def cache_dir():
    return _xdg("XDG_CACHE_HOME", "~/.cache") / APP


def ensure(path, mode=0o755):
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


# ---- specific files ----
def config_file():
    return config_dir() / "config.json"


def key_file():
    return config_dir() / "gemini_key"


def index_db():
    return data_dir() / "index.db"


def agy_workdir():
    return cache_dir() / "agy-work"
