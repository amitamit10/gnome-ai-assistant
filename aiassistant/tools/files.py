"""Searching the user's own files and (safely) opening them from widgets."""
import base64
import io
import os
import subprocess

from .. import config
from ..search import index, query

HOME = os.path.expanduser("~")
_thumbs = {}


def short(path):
    return path.replace(HOME, "~", 1) if path.startswith(HOME) else path


def thumbnail(path, size=220):
    """Small JPEG data URI for an image file (cached), or None."""
    if path in _thumbs:
        return _thumbs[path]
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=72)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        uri = None
    if len(_thumbs) > 300:
        _thumbs.clear()
    _thumbs[path] = uri
    return uri


def search(q, searcher=None):
    """Returns (compact result for the model, data for the `file_results` widget)."""
    hits = (searcher or query.shared()).search(q)
    items = []
    for h in hits:
        it = {"kind": h["kind"], "name": os.path.basename(h["path"]), "path": short(h["path"])}
        if h["kind"] == "text":
            it["snippet"] = " ".join(h["label"].split())[:200]
        elif h["kind"] == "image":
            it["thumb"] = thumbnail(h["path"]) or ""
            if not it["thumb"]:
                del it["thumb"]
        elif h["kind"] == "video":
            it["snippet"] = f"at {h['label']}"
        items.append(it)
    for_model = [{k: v for k, v in it.items() if k != "thumb"} for it in items]
    return {"results": for_model, "note": "a visual grid of these files is already displayed"}, {"title": "Files", "items": items}


def allowed(path):
    """True only for a real file under a configured index root, not hidden, of an indexable type."""
    p = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(p) or index.kind_of(p) is None:
        return False
    roots = [os.path.realpath(r) for r in config.expand_roots()]
    if not any(p == r or p.startswith(r + os.sep) for r in roots):
        return False
    return not any(part.startswith(".") for part in p.split(os.sep) if part)


def open_file(path):
    """Open an indexed file with the desktop's default application. Returns True if it was allowed and launched."""
    if not allowed(path):
        return False
    subprocess.Popen(["xdg-open", os.path.realpath(os.path.expanduser(path))], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True
