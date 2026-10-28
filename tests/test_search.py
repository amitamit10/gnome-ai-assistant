import os

import numpy as np
import pytest

from aiassistant import config, paths
from aiassistant.search import index, query


class FakeEmbedder:
    """Deterministic 8-dim 'model': a text maps to the basis vector chosen by its first keyword."""
    model_id = "fake/model"
    multimodal = False
    model = None
    WORDS = ["apple", "banana", "cherry", "date"]

    def _vec(self, text):
        v = np.zeros(8, dtype=np.float32)
        for i, w in enumerate(self.WORDS):
            if w in text.lower():
                v[i] = 1
        if not v.any():
            v[7] = 1
        return v / np.linalg.norm(v)

    def documents(self, chunks, title=""):
        return np.stack([self._vec(c) for c in chunks])

    def queries(self, texts):
        return np.stack([self._vec(t) for t in texts])

    def images(self, ims):
        return np.stack([self._vec("apple") for _ in ims])

    def load(self):
        return None

    def unload(self):
        pass


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "home" / "Docs"
    (root / "node_modules").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "sub").mkdir()
    (root / "a.md").write_text("Apple pie recipe. " * 5)
    (root / "b.md").write_text("Banana bread notes. " * 5)
    (root / "sub" / "copy_of_a.md").write_text("Apple pie recipe. " * 5)   # duplicate content
    (root / "c.txt").write_text("Cherry tree facts. " * 5)
    (root / "node_modules" / "skip.md").write_text("apple")
    (root / ".hidden" / "skip.md").write_text("apple")
    (root / "run.py").write_text("print('apple')")
    config.save({"index_roots": [str(root)], "embed_model": "fake/model"})
    return root


def test_walk_skips_tooling_hidden_and_unsupported(docs):
    names = sorted(os.path.relpath(p, docs) for p, k in index.walk())
    assert names == ["a.md", "b.md", "c.txt", os.path.join("sub", "copy_of_a.md")]


def test_chunking_overlaps_and_covers_text():
    text = "word " * 1000
    cs = list(index.chunks(text))
    assert len(cs) > 3 and all(len(c) <= index.CHUNK for c in cs)
    assert index.chunks.__name__ == "chunks"


def test_build_is_incremental(docs):
    emb = FakeEmbedder()
    logs = []
    index.build(log=logs.append, embedder=emb)
    assert index.stats()["text"]["files"] == 4
    logs.clear()
    index.build(log=logs.append, embedder=emb)
    assert logs[0].startswith("0 new/changed")
    (docs / "b.md").write_text("Banana bread notes, updated. " * 5)
    os.utime(docs / "b.md", (os.path.getmtime(docs / "b.md") + 5,) * 2)
    (docs / "c.txt").unlink()
    logs.clear()
    index.build(log=logs.append, embedder=emb)
    assert logs[0] == "1 new/changed files, 1 removed"
    assert index.stats()["text"]["files"] == 3


def test_changing_the_embedding_model_resets_the_index(docs):
    index.build(log=lambda m: None, embedder=FakeEmbedder())
    assert index.stats()
    config.save({"embed_model": "another/model"})
    assert index.stats() == {}   # vectors from different models must never be mixed


def test_search_ranks_by_meaning_and_collapses_duplicates(docs, monkeypatch):
    index.build(log=lambda m: None, embedder=FakeEmbedder())
    s = query.Searcher(embedder=FakeEmbedder())
    hits = s.search("apple dessert", use_llm=False)
    assert hits[0]["path"].endswith("a.md") or hits[0]["path"].endswith("copy_of_a.md")
    assert len([h for h in hits if "apple" in h["label"].lower()]) == 1, "identical chunks from copies appear once"
    assert s.search("banana", use_llm=False)[0]["path"].endswith("b.md")
    assert s.search("cherry", use_llm=False)[0]["path"].endswith("c.txt")


def test_search_without_an_index_explains(docs):
    with pytest.raises(FileNotFoundError):
        query.Searcher(embedder=FakeEmbedder()).search("x", use_llm=False)


def test_per_kind_limits_and_superseded_requests(docs):
    index.build(log=lambda m: None, embedder=FakeEmbedder())
    s = query.Searcher(embedder=FakeEmbedder())
    assert len(s.search("apple", per_kind={"text": 1}, use_llm=False)) == 1
    assert s.search("apple", use_llm=False, is_current=lambda: False) == []


def test_text_candidates_are_distinct_chunks(docs):
    index.build(log=lambda m: None, embedder=FakeEmbedder())
    cands = query.Searcher(embedder=FakeEmbedder()).text_candidates("banana", n=5, use_llm=False)
    assert cands[0][1].endswith("b.md") and [c[0] for c in cands] == list(range(len(cands)))
    assert len({c[2][:300] for c in cands}) == len(cands)


def test_index_follows_changes_made_after_the_searcher_loaded(docs):
    emb = FakeEmbedder()
    index.build(log=lambda m: None, embedder=emb)
    s = query.Searcher(embedder=emb)
    assert not any("date" in h["label"].lower() for h in s.search("date", use_llm=False))
    (docs / "d.md").write_text("Date palm trees. " * 5)
    index.build(log=lambda m: None, embedder=emb)
    assert any(h["path"].endswith("d.md") for h in s.search("date", use_llm=False))


def test_rewrite_is_a_noop_without_a_key():
    assert query.rewrite("anything here") == ["anything here"]


def test_export_and_import_roundtrip(docs, tmp_path):
    out = index.export_bundle(out=tmp_path / "bundle", log=lambda m: None)
    assert out.endswith(".zip") and os.path.exists(out)
    import json
    meta = json.load(open(tmp_path / "bundle" / "items.json"))
    assert meta["model"] == "fake/model" and len(meta["files"]) == 4
    vecs = FakeEmbedder().documents([i["text"] for i in meta["items"]])
    np.save(tmp_path / "v.npy", vecs)
    index.import_vectors(tmp_path / "v.npy", bundle_dir=tmp_path / "bundle", log=lambda m: None)
    assert index.stats()["text"]["files"] == 4
    s = query.Searcher(embedder=FakeEmbedder())
    assert s.search("banana", use_llm=False)[0]["path"].endswith("b.md")
