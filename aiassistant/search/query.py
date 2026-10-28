"""Query side of semantic search: holds the vectors in memory, loads the embedding model on demand, unloads it when idle.

One shared Searcher serves the chat tools and the GNOME overview search provider.
"""
import hashlib
import os
import sqlite3
import threading
import time

from .. import paths
from ..llm import gemini
from . import embed

_rewrites = {}


def rewrite(query):
    """[query] plus up to two cleaned/translated variants from Gemini (cached; just [query] without a key or quota)."""
    k = query.lower()
    if k in _rewrites:
        return _rewrites[k]
    out = [query]
    r = gemini.json_call(
        "Rewrite this search query for semantic search over someone's personal files (notes, docs, screenshots, "
        "photos, videos). Fix typos; if it is not English, add an English translation; keep the meaning. "
        f"Return JSON {{\"queries\": [at most 2 short variants]}}. Query: {query!r}")
    if isinstance(r, dict) and isinstance(r.get("queries"), list):
        out += [x for x in r["queries"][:2] if isinstance(x, str) and x.strip() and x != query]
    _rewrites[k] = out
    return out


class Searcher:
    def __init__(self, embedder=None):
        self.embedder = embedder or embed.Embedder()
        self.lock = threading.Lock()
        self.mat = self.rows = self.kinds = None
        self.db_mtime = 0.0
        self.last_used = time.time()

    # ---- index in memory ----
    def _load_index(self):
        db_file = paths.index_db()
        if not db_file.exists():
            raise FileNotFoundError("no index yet: run `aiassistant index`")
        m = os.path.getmtime(db_file)
        if self.mat is not None and m == self.db_mtime:
            return
        import numpy as np
        db = sqlite3.connect(db_file, timeout=30)
        rows = db.execute("SELECT path, kind, label, vec FROM chunks").fetchall()
        db.close()
        if not rows:
            raise FileNotFoundError("the index is empty: run `aiassistant index`")
        self.rows = [(r[0], r[1], r[2]) for r in rows]
        self.mat = np.stack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
        self.kinds = np.array([r[1] for r in rows])
        self.db_mtime = m

    def warm(self):
        with self.lock:
            self._load_index()
            self.embedder.load()
            self.last_used = time.time()

    def unload_if_idle(self, after=15 * 60):
        if self.lock.acquire(blocking=False):
            try:
                if self.embedder.model is not None and time.time() - self.last_used > after:
                    self.embedder.unload()
                    self.mat = self.rows = self.kinds = None
            finally:
                self.lock.release()

    # ---- search ----
    def _scores(self, variants):
        qv = self.embedder.queries(variants)
        return (self.mat @ qv.T).max(axis=1)

    def search(self, query, per_kind=None, use_llm=True, is_current=lambda: True):
        """Interleaved hits [{kind, path, label, score}], best per kind first. Duplicate files/chunks collapsed."""
        per_kind = per_kind or {"image": 3, "text": 3, "video": 1}
        variants = rewrite(query) if use_llm else [query]  # network call, outside the lock
        with self.lock:
            if not is_current():
                return []
            self._load_index()
            self.last_used = time.time()
            import numpy as np
            sims = self._scores(variants)
            picked, seen = {k: [] for k in per_kind}, set()
            for i in np.argsort(-sims)[:600]:
                path, kind, label = self.rows[i]
                if kind not in picked or len(picked[kind]) >= per_kind[kind] or not os.path.exists(path):
                    continue
                key = hashlib.md5(label[:300].encode()).hexdigest() if kind == "text" else (os.path.basename(path), os.path.getsize(path), kind)
                if key in seen:
                    continue
                seen.add(key)
                picked[kind].append({"kind": kind, "path": path, "label": label, "score": float(sims[i])})
                if all(len(picked[k]) >= per_kind[k] for k in per_kind):
                    break
        out = []
        for n in range(max((len(v) for v in picked.values()), default=0)):
            for k in ("image", "text", "video"):
                if k in picked and n < len(picked[k]):
                    out.append(picked[k][n])
        return out

    def text_candidates(self, question, n=12, use_llm=True):
        """Best distinct text chunks for answering a question: [(id, path, chunk)]."""
        variants = rewrite(question) if use_llm else [question]
        with self.lock:
            self._load_index()
            self.last_used = time.time()
            import numpy as np
            sims = np.where(self.kinds == "text", self._scores(variants), -1)
            cands, seen = [], set()
            for i in np.argsort(-sims)[:200]:
                path, kind, label = self.rows[i]
                if kind != "text" or label[:300] in seen:
                    continue
                seen.add(label[:300])
                cands.append((len(cands), path, label))
                if len(cands) >= n:
                    break
        return cands


_shared = None


def shared():
    global _shared
    if _shared is None:
        _shared = Searcher()
    return _shared
