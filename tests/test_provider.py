import pytest

from aiassistant import config
from aiassistant.search import ask, provider, query


@pytest.mark.parametrize("terms,expected", [
    (["firefox"], (None, "")),
    (["google", "chrome"], (None, "")),                                   # two words: app name, stay silent
    (["screenshots", "of", "settings"], ("search", "screenshots of settings")),   # 3+ words: automatic
    (["?", "flowers"], ("search", "flowers")),
    (["AI", "invoice", "march"], ("search", "invoice march")),
    (["?"], ("warm", "")),                                                 # just the trigger: preload the model
    (["ask", "what", "caused", "the", "outage"], ("ask", "what caused the outage")),
    (["ask", "why"], (None, "")),                                          # too short to be a real question
    ([], (None, "")),
])
def test_parse(terms, expected):
    assert provider.parse(terms) == expected


def test_meta_formats():
    assert provider.meta_for("image|/h/a.png|")["gicon"] == "/h/a.png"
    assert provider.meta_for("video|/h/v.mp4|80s")["description"].endswith("@80s")
    t = provider.meta_for("text|/h/n.md|some   long\ntext")
    assert t["name"] == "n.md" and "some long text" in t["description"] and t["gicon"] == "text-x-generic"
    a = provider.meta_for("answer|/h/n.md|It was DNS.")
    assert a["name"] == "Answer: It was DNS." and a["gicon"] == "dialog-information"
    assert provider.meta_for("text|/h/x|a|b|c")["name"] == "x"  # '|' inside the label is fine


class FakeSearcher:
    def __init__(self):
        self.calls = []

    def search(self, q, per_kind=None, use_llm=True, is_current=lambda: True):
        self.calls.append(q)
        return [{"kind": "text", "path": "/h/n.md", "label": "hello", "score": .9}, {"kind": "image", "path": "/h/a.png", "label": "", "score": .8}]

    def warm(self):
        self.calls.append("warm")


def test_short_queries_never_touch_the_search_engine(monkeypatch):
    fs = FakeSearcher()
    monkeypatch.setattr(query, "shared", lambda: fs)
    p = provider.Provider()
    assert p.results(["firefox"]) == [] and p.results(["two", "words"]) == [] and fs.calls == []


def test_results_are_ids(monkeypatch):
    fs = FakeSearcher()
    monkeypatch.setattr(query, "shared", lambda: fs)
    assert provider.Provider().results(["a", "long", "query"]) == ["text|/h/n.md|hello", "image|/h/a.png|"]


def test_missing_index_returns_nothing_instead_of_crashing(monkeypatch):
    class NoIndex(FakeSearcher):
        def search(self, *a, **k):
            raise FileNotFoundError("no index yet")
    monkeypatch.setattr(query, "shared", lambda: NoIndex())
    assert provider.Provider().results(["?", "anything"]) == []


def test_ask_puts_the_answer_first(monkeypatch):
    monkeypatch.setattr(ask, "answer", lambda q: ("It was DNS.", ["/h/a.md", "/h/b.md"]))
    ids = provider.Provider().results(["ask", "what", "caused", "it"])
    assert ids[0] == "answer|/h/a.md|It was DNS." and ids[1:] == ["text|/h/a.md|", "text|/h/b.md|"]


def test_debounce_only_when_a_key_is_configured(monkeypatch, fake_key):
    slept = []
    monkeypatch.setattr(provider.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(query, "shared", lambda: FakeSearcher())
    p = provider.Provider()
    p.results(["a", "b", "c"])
    assert slept == [0.5]


def test_activate_only_opens_allowed_files(monkeypatch):
    opened = []
    monkeypatch.setattr(provider.files, "open_file", lambda path: opened.append(path))
    provider.Provider().activate("text|/h/n.md|snippet")
    assert opened == ["/h/n.md"]
