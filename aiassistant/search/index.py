"""Build and maintain the semantic index (SQLite: files, chunks with float32 vectors).

Indexed: documents (md, txt, pdf, docx, pptx, odt), images, and video frames (one every 10 s). Skipped: hidden folders,
node_modules and other tooling directories, tiny images (icons) and huge files. Incremental by modification time.
For many files on a CPU use the GPU path: `aiassistant index --export`, run the notebook in docs/, then
`aiassistant index --import vectors.npy`.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

from .. import config, paths

TEXT_EXTS = {".md", ".txt", ".pdf", ".docx", ".pptx", ".odt"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov"}
SKIP_DIRS = {"node_modules", ".git", ".next", "venv", ".venv", "__pycache__", "dist", "build", ".cache"}
MAX_BYTES = 20 * 1024 * 1024
MIN_IMAGE_BYTES = 8 * 1024
VIDEO_FRAME_EVERY = 10  # seconds
VIDEO_MAX_FRAMES = 60
CHUNK, OVERLAP = 900, 150


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    return "text" if ext in TEXT_EXTS else "image" if ext in IMAGE_EXTS else "video" if ext in VIDEO_EXTS else None


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt"):
        return open(path, errors="ignore").read()
    if ext == ".pdf":
        if not shutil.which("pdftotext"):
            return ""
        return subprocess.run(["pdftotext", "-q", path, "-"], capture_output=True, text=True, errors="ignore", timeout=60).stdout
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist()
                 if n == "word/document.xml" or n == "content.xml" or re.match(r"ppt/slides/slide\d+\.xml", n)]
        xml = " ".join(z.read(n).decode("utf8", "ignore") for n in sorted(names))
    return re.sub(r"<[^>]+>", " ", xml)


def chunks(text):
    text = re.sub(r"\s+", " ", text).strip()
    i = 0
    while i < len(text):
        yield text[i:i + CHUNK]
        i += CHUNK - OVERLAP


def video_frames(path):
    """Yield (seconds, PIL.Image) sampled every VIDEO_FRAME_EVERY seconds (needs the `av` package)."""
    import av
    with av.open(path) as c:
        s = c.streams.video[0]
        dur = float(c.duration / 1e6) if c.duration else 0
        for t in list(range(0, max(int(dur), 1), VIDEO_FRAME_EVERY))[:VIDEO_MAX_FRAMES]:
            c.seek(int(t * 1e6))
            for f in c.decode(s):
                img = f.to_image()
                img.thumbnail((768, 768))
                yield t, img
                break


def walk(roots=None):
    for root in roots or config.expand_roots():
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
            for f in files:
                p = os.path.join(d, f)
                k = kind_of(p)
                if not k:
                    continue
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if (k == "image" and sz < MIN_IMAGE_BYTES) or (k != "video" and sz > MAX_BYTES):
                    continue
                yield p, k


def connect(model_id=None):
    paths.ensure(paths.data_dir())
    db = sqlite3.connect(paths.index_db(), timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    want = model_id or config.get("embed_model")
    cur = db.execute("SELECT v FROM meta WHERE k='model'").fetchone()
    if cur and cur[0] != want:  # vectors from different models cannot be mixed
        db.executescript("DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS chunks;")
    db.execute("INSERT OR REPLACE INTO meta VALUES('model', ?)", (want,))
    db.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT, kind TEXT, label TEXT, vec BLOB)")
    db.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")
    db.commit()  # never leave a write transaction open: other connections would get "database is locked"
    return db


def stats():
    db = connect()
    try:
        return {k: {"files": f, "vectors": n} for k, n, f in db.execute("SELECT kind, COUNT(*), COUNT(DISTINCT path) FROM chunks GROUP BY kind")}
    finally:
        db.close()


def _pending(db):
    seen = dict(db.execute("SELECT path, mtime FROM files"))
    current, todo = set(), []
    for p, k in walk():
        current.add(p)
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if seen.get(p) != m:
            todo.append((p, k, m))
    gone = set(seen) - current
    return todo, gone


def build(log=print, embedder=None):
    """Index new and changed files with the configured embedding model (slow on CPU)."""
    from PIL import Image
    from .embed import Embedder
    db = connect()
    todo, gone = _pending(db)
    for p in gone:
        db.execute("DELETE FROM chunks WHERE path=?", (p,))
        db.execute("DELETE FROM files WHERE path=?", (p,))
    log(f"{len(todo)} new/changed files, {len(gone)} removed")
    if not todo:
        db.commit()
        db.close()
        return
    emb = embedder or Embedder()
    todo.sort(key=lambda x: {"text": 0, "image": 1, "video": 2}[x[1]])  # fast things first
    t0 = time.time()
    for n, (p, k, m) in enumerate(todo, 1):
        rows = []
        try:
            if k == "text":
                cs = list(chunks(extract(p)))[:400]
                if cs:
                    vs = emb.documents(cs, title=os.path.basename(p))
                    rows = [(p, "text", c, v.tobytes()) for c, v in zip(cs, vs)]
            elif k == "image" and emb.multimodal:
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    im.thumbnail((1024, 1024))
                    rows = [(p, "image", "", emb.images([im])[0].tobytes())]
            elif k == "video" and emb.multimodal:
                fr = list(video_frames(p))
                if fr:
                    vs = emb.images([im for _, im in fr])
                    rows = [(p, "video", f"{t}s", v.tobytes()) for (t, _), v in zip(fr, vs)]
        except Exception as e:
            log(f"skip {p}: {type(e).__name__}: {str(e)[:80]}")
        db.execute("DELETE FROM chunks WHERE path=?", (p,))
        db.executemany("INSERT INTO chunks(path,kind,label,vec) VALUES(?,?,?,?)", rows)
        db.execute("INSERT OR REPLACE INTO files VALUES(?,?)", (p, m))
        if n % 20 == 0:
            db.commit()
            el = time.time() - t0
            log(f"  {n}/{len(todo)}  {el:.0f}s  (~{el / n * (len(todo) - n) / 60:.0f} min left)")
    db.commit()
    db.close()
    log("index up to date")


# ---------------- GPU path: export a bundle, embed on Colab, import the vectors ----------------
def export_bundle(out=None, log=print):
    from PIL import Image
    out = str(out or paths.cache_dir() / "bundle")
    db = connect()
    seen = dict(db.execute("SELECT path, mtime FROM files"))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "media"))
    items, files, n = [], [], 0
    for p, k in walk():
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if seen.get(p) == m:
            continue
        files.append([p, m])
        try:
            if k == "text":
                for c in list(chunks(extract(p)))[:400]:
                    items.append({"path": p, "kind": "text", "label": c, "text": f"title: {os.path.basename(p)} | text: {c}"})
            else:
                pics = [("", Image.open(p))] if k == "image" else [(f"{t}s", im) for t, im in video_frames(p)]
                for lab, im in pics:
                    n += 1
                    im = im.convert("RGB")
                    im.thumbnail((768, 768))
                    fn = f"media/{n}.jpg"
                    im.save(os.path.join(out, fn), quality=85)
                    items.append({"path": p, "kind": k, "label": lab, "media": fn})
        except Exception as e:
            log(f"skip {p}: {type(e).__name__}: {str(e)[:80]}")
    db.close()
    with open(os.path.join(out, "items.json"), "w") as f:
        json.dump({"model": config.get("embed_model"), "items": items, "files": files}, f)
    shutil.make_archive(out, "zip", out)
    log(f"{len(items)} items from {len(files)} files -> {out}.zip ({os.path.getsize(out + '.zip') / 1e6:.0f} MB)")
    return out + ".zip"


def import_vectors(vectors_npy, bundle_dir=None, log=print):
    import numpy as np
    meta = json.load(open(os.path.join(bundle_dir or paths.cache_dir() / "bundle", "items.json")))
    vecs = np.load(vectors_npy).astype(np.float32)
    assert len(vecs) == len(meta["items"]), "vectors/items length mismatch"
    db = connect(meta["model"])
    for p, _ in meta["files"]:
        db.execute("DELETE FROM chunks WHERE path=?", (p,))
    db.executemany("INSERT INTO chunks(path,kind,label,vec) VALUES(?,?,?,?)",
                   [(it["path"], it["kind"], it["label"], v.tobytes()) for it, v in zip(meta["items"], vecs)])
    db.executemany("INSERT OR REPLACE INTO files VALUES(?,?)", meta["files"])
    db.commit()
    db.close()
    log(f"imported {len(vecs)} vectors for {len(meta['files'])} files")
