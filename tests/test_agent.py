import json

import pytest

from aiassistant import agent, config
from aiassistant.llm import agy as agy_mod, gemini
from aiassistant.tools import registry, weather
from test_registry import FORECAST


def reply(parts):
    return {"candidates": [{"content": {"role": "model", "parts": parts}}]}


def scripted(responses, seen=None):
    it = iter(responses)

    def generate(contents, tools=None, system=None, **kw):
        if seen is not None:
            seen.append(json.loads(json.dumps(contents)))
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return "gemini-test", r
    return generate


class FakeAgy:
    """Stands in for the sandboxed Antigravity process: scripted replies, records what it was sent."""
    sent = []
    script = []

    def __init__(self):
        pass

    def turn(self, message, timeout=150):
        FakeAgy.sent.append(message)
        return FakeAgy.script.pop(0)

    def close(self):
        pass

    def idle_close(self, after=600):
        pass


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(weather, "forecast", lambda city: FORECAST)
    FakeAgy.sent, FakeAgy.script = [], []
    monkeypatch.setattr(agy_mod, "Agy", FakeAgy)


def test_tool_loop_returns_widget_text_and_followups(monkeypatch):
    seen, status = [], []
    call_part = {"functionCall": {"name": "get_weather", "args": {"city": "Jerusalem"}}, "thoughtSignature": "SIG"}
    monkeypatch.setattr(gemini, "generate", scripted([
        reply([call_part]),
        reply([{"text": "Sunny and 24°C.\nFOLLOWUPS: Tomorrow? | This week?"}]),
    ], seen))
    chat = agent.Chat()
    r = chat.ask("weather in Jerusalem", lambda s: status.append(s))
    assert r["text"] == "Sunny and 24°C." and r["followups"] == ["Tomorrow?", "This week?"]
    assert len(r["widgets"]) == 1 and r["widgets"][0]["widget"] == "weather" and r["model"] == "gemini-test"
    assert "Checking the weather" in status
    # the model turn is replayed verbatim (Gemini 3 needs the thought signature) and the tool result is sent back
    second = seen[1]
    assert second[1]["parts"][0]["thoughtSignature"] == "SIG"
    assert second[2]["parts"][0]["functionResponse"]["name"] == "get_weather"


def test_multiple_questions_keep_context_but_not_widgets(monkeypatch):
    monkeypatch.setattr(gemini, "generate", scripted([
        reply([{"functionCall": {"name": "get_weather", "args": {"city": "x"}}}]), reply([{"text": "one"}]), reply([{"text": "two"}])]))
    chat = agent.Chat()
    assert len(chat.ask("a", lambda s: None)["widgets"]) == 1
    r2 = chat.ask("b", lambda s: None)
    assert r2["text"] == "two" and r2["widgets"] == []


def test_failing_tool_becomes_a_result_the_model_can_see(monkeypatch):
    monkeypatch.setattr(weather, "forecast", lambda c: (_ for _ in ()).throw(TimeoutError("offline")))
    seen = []
    monkeypatch.setattr(gemini, "generate", scripted([
        reply([{"functionCall": {"name": "get_weather", "args": {"city": "x"}}}]), reply([{"text": "Sorry, offline."}])], seen))
    assert agent.Chat().ask("q", lambda s: None)["text"] == "Sorry, offline."
    assert "TimeoutError" in json.dumps(seen[1][2])


def test_runaway_tool_loop_is_stopped(monkeypatch):
    loop = reply([{"functionCall": {"name": "get_weather", "args": {"city": "x"}}}])
    monkeypatch.setattr(gemini, "generate", scripted([loop] * 10))
    assert "stuck" in agent.Chat().ask("q", lambda s: None)["text"]


def test_quota_exhausted_falls_back_to_the_sandboxed_antigravity(monkeypatch):
    monkeypatch.setattr(agy_mod, "available", lambda: True)
    monkeypatch.setattr(gemini, "generate", scripted([gemini.QuotaExhausted("used up")]))
    FakeAgy.script = ['Sure. {"tool": "get_weather", "args": {"city": "Jerusalem"}}', '{"final": "It is sunny.\\nFOLLOWUPS: more?"}']
    status = []
    chat = agent.Chat()
    r = chat.ask("weather?", status.append)
    assert r["text"] == "It is sunny." and r["followups"] == ["more?"] and len(r["widgets"]) == 1
    assert chat.model.startswith("antigravity:")
    assert any("switching to Antigravity" in s for s in status)
    first = FakeAgy.sent[0]
    assert "PROTOCOL" in first and "Do NOT use any built-in tools" in first and "get_weather" in first
    assert FakeAgy.sent[1].startswith("TOOL_RESULT get_weather:")
    assert chat.contents == [], "the failed API turn must not stay in the Gemini history"


def test_provider_api_never_uses_antigravity(monkeypatch):
    config.save({"provider": "api"})
    monkeypatch.setattr(agy_mod, "available", lambda: True)
    monkeypatch.setattr(gemini, "generate", scripted([gemini.QuotaExhausted("used up")]))
    with pytest.raises(gemini.QuotaExhausted):
        agent.Chat().ask("q", lambda s: None)
    assert FakeAgy.sent == []


def test_quota_error_surfaces_when_antigravity_is_unavailable(monkeypatch):
    monkeypatch.setattr(agy_mod, "available", lambda: False)
    monkeypatch.setattr(gemini, "generate", scripted([gemini.QuotaExhausted("used up")]))
    with pytest.raises(gemini.QuotaExhausted):
        agent.Chat().ask("q", lambda s: None)


def test_provider_agy_skips_the_api_entirely(monkeypatch):
    config.save({"provider": "agy"})
    monkeypatch.setattr(gemini, "generate", lambda *a, **k: pytest.fail("API must not be called"))
    FakeAgy.script = ['{"final": "hi"}']
    assert agent.Chat().ask("q", lambda s: None)["text"] == "hi"


def test_agy_protocol_parsing_is_forgiving():
    f = agent.Chat._first_json
    assert f('```json\n{"final": "x"}\n```') == {"final": "x"}
    assert f('thinking... {"tool": "a", "args": {"n": {"deep": 1}}} trailing') == {"tool": "a", "args": {"n": {"deep": 1}}}
    assert f("no json here") is None and f("{broken") is None


def test_agy_plain_text_answer_is_accepted(monkeypatch):
    config.save({"provider": "agy"})
    FakeAgy.script = ["just a plain sentence"]
    assert agent.Chat().ask("q", lambda s: None)["text"] == "just a plain sentence"


def test_system_prompt_lists_the_widget_catalogue_and_rules():
    p = agent.system_prompt()
    for needle in ("get_weather", "show_widgets", "gauge", "choices", "FOLLOWUPS", "Never invent data", "battery-full"):
        assert needle in p
    assert "create_widget" not in p and "find_icon" not in p and "<div" not in p


def test_followup_parsing():
    assert agent._split_followups("Hi\nFOLLOWUPS: a | b | c | d") == ("Hi", ["a", "b", "c"])
    assert agent._split_followups("plain") == ("plain", [])


def test_reset_clears_history_and_agy(monkeypatch):
    chat = agent.Chat()
    chat.contents = [1]
    chat.agy = FakeAgy()
    chat.reset()
    assert chat.contents == [] and chat.agy is None
