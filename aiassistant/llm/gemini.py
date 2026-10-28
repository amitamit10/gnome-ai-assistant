"""Gemini REST client: model fallback, thinking disabled for speed, and errors that explain themselves."""
import http.client
import json
import socket
import sys
import time
import urllib.error
import urllib.request

from .. import config

BASE = "https://generativelanguage.googleapis.com/v1beta/"


class GeminiError(RuntimeError):
    pass


class NoKey(GeminiError):
    pass


class QuotaExhausted(GeminiError):
    """Every model returned 429 (free tier: ~20 requests/day/model) or was unavailable."""


def call(path, body=None, timeout=60):
    key = config.gemini_key()
    if not key:
        raise NoKey("no Gemini API key configured (see README: ~/.config/gnome-ai-assistant/gemini_key)")
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def models():
    return config.get("models")


_no_thinking = set()  # models that rejected thinkingConfig (400): skip the doomed first try next time
_cooldown = {}  # model -> time.monotonic() until which it is tried last (it just failed or stalled)
LOG = False  # set AIASSISTANT_DEBUG=1 to print every attempt


def _skip(m):
    return _cooldown.get(m, 0) > time.monotonic()


def _log(m, what, t0):
    """Failures and slow attempts go to stderr (the journal when run by D-Bus); AIASSISTANT_DEBUG=1 logs every attempt."""
    import os
    took = time.monotonic() - t0
    if LOG or os.environ.get("AIASSISTANT_DEBUG") or what != "ok" or took > 6:
        print(f"gemini {m}: {what} after {took:.1f}s", file=sys.stderr, flush=True)


def generate(contents, tools=None, system=None, temperature=0.4, timeout=30, mime=None):
    """One generateContent call, trying each configured model. Returns (model, response).

    Falls through to the next model on 404/429/500/503 and on a stalled connection (each attempt is capped at `timeout`
    seconds); a model that failed is tried last for a few minutes so every turn does not pay for the same dead end.
    A dropped connection gets one immediate retry. A 400 retries the model without the thinking setting.
    """
    last, daily = None, False
    order = models()
    order = [m for m in order if not _skip(m)] + [m for m in order if _skip(m)]
    for m in order:
        for thinking in ((False,) if m in _no_thinking else (True, False)):
            gc = {"temperature": temperature}
            if mime:
                gc["responseMimeType"] = mime
            if thinking:
                gc["thinkingConfig"] = {"thinkingBudget": 0}
            body = {"contents": contents, "generationConfig": gc}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            if tools:
                body["tools"] = tools
            t0 = time.monotonic()
            again = False  # True: retry this model without the thinking setting
            for attempt in (1, 2):
                try:
                    r = call(f"models/{m}:generateContent", body, timeout)
                    _log(m, "ok", t0)
                    return m, r
                except urllib.error.HTTPError as e:
                    if e.code == 400 and thinking:
                        _log(m, "400 (retrying without thinking config)", t0)
                        _no_thinking.add(m)
                        again = True
                        break
                    last = e.code
                    per_day = False
                    if e.code == 429:
                        per_day = "PerDay" in e.read().decode("utf8", "ignore")
                        daily = daily or per_day
                    _log(m, f"HTTP {e.code}", t0)
                    if e.code in (400, 404, 429, 500, 503):
                        _cooldown[m] = time.monotonic() + (3600 if per_day else 180)
                        break
                    raise GeminiError(f"HTTP {e.code} from {m}") from e
                except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError) as e:
                    _log(m, type(e).__name__, t0)
                    if attempt == 1:
                        time.sleep(0.5)
                        continue  # the connection dropped: retry the same model once
                    last = type(e).__name__
                    _cooldown[m] = time.monotonic() + 60
                    break
                except (TimeoutError, socket.timeout, urllib.error.URLError, http.client.HTTPException, OSError) as e:
                    _log(m, type(e).__name__, t0)
                    last = type(e).__name__
                    _cooldown[m] = time.monotonic() + 120  # stalled or unreachable: try the next model, do not wait again
                    break
            if not again:
                break
    if daily:
        raise QuotaExhausted("Today's free Gemini quota is used up on every model (the free tier allows about 20 "
                             "requests per day per model). It resets daily; enabling billing on the API key's "
                             "Google Cloud project removes the limit.")
    if isinstance(last, str):
        raise GeminiError(f"Can't reach Gemini ({last}). Check the network and try again.")
    raise QuotaExhausted(f"Gemini is busy right now (HTTP {last}). Try again in a minute.")


def text_of(response):
    return "".join(p.get("text", "") for p in response["candidates"][0]["content"]["parts"])


def json_call(prompt, timeout=25):
    """A prompt that must answer in JSON; returns the parsed object or None on any failure (never raises)."""
    try:
        _, r = generate([{"parts": [{"text": prompt}]}], temperature=0, timeout=timeout, mime="application/json")
        return json.loads(text_of(r))
    except Exception:
        return None


def list_models():
    return {m["name"].split("/")[-1]: m.get("supportedGenerationMethods", []) for m in call("models?pageSize=200")["models"]}
