import threading
import time

from aiassistant.llm import gemini
from aiassistant.session import Session


class FakeChat:
    model = "fake"

    def __init__(self, reply=None, exc=None, gate=None):
        self.reply, self.exc, self.gate, self.resets = reply or {"text": "hi", "widgets": [], "followups": []}, exc, gate, 0

    def ask(self, text, status):
        status("Working")
        if self.gate:
            self.gate.wait(5)
        if self.exc:
            raise self.exc
        return dict(self.reply)

    def reset(self):
        self.resets += 1


def run(session, text):
    got, done = {"status": [], "reply": None}, threading.Event()
    err = session.ask(text, got["status"].append, lambda r: (got.__setitem__("reply", r), done.set()))
    return err, got, done


def test_a_turn_reports_progress_and_the_reply_and_is_remembered():
    s = Session(FakeChat())
    err, got, done = run(s, "hello")
    assert err is None and done.wait(5)
    assert got["status"] == ["Working"] and got["reply"]["text"] == "hi"
    assert [i["role"] for i in s.display] == ["user", "bot"] and not s.busy and s.status == ""
    assert s.snapshot()["model"] == "fake"


def test_a_second_question_while_busy_is_refused():
    gate = threading.Event()
    s = Session(FakeChat(gate=gate))
    _, _, done = run(s, "one")
    time.sleep(0.1)
    assert s.busy and s.snapshot()["status"] == "Working"
    err, _, _ = run(s, "two")
    assert "Still working" in err
    assert not s.reset(), "cannot clear the conversation mid-turn"
    gate.set()
    assert done.wait(5)
    assert len(s.display) == 2


def test_errors_become_a_reply_not_a_crash():
    s = Session(FakeChat(exc=gemini.QuotaExhausted("used up")))
    _, got, done = run(s, "q")
    assert done.wait(5) and got["reply"] == {"error": "used up"}
    s2 = Session(FakeChat(exc=RuntimeError("boom")))
    _, got2, done2 = run(s2, "q")
    assert done2.wait(5) and got2["reply"] == {"error": "boom"} and not s2.busy


def test_empty_question_is_rejected_and_reset_clears():
    chat = FakeChat()
    s = Session(chat)
    assert run(s, "   ")[0] == "empty question"
    _, _, done = run(s, "x")
    done.wait(5)
    time.sleep(0.05)
    assert s.reset() and s.display == [] and chat.resets == 1
