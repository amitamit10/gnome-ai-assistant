"""Web search through Gemini's Google Search grounding (needs the Gemini API key)."""
from ..llm import gemini


def search(query):
    _, r = gemini.generate([{"role": "user", "parts": [{"text": query}]}], tools=[{"google_search": {}}],
                           system="Answer briefly and factually using search. Include key numbers and dates.", timeout=40)
    c = r["candidates"][0]
    srcs = [w["web"] for w in c.get("groundingMetadata", {}).get("groundingChunks", []) if "web" in w][:5]
    return {"answer": gemini.text_of(r), "sources": [{"title": s.get("title"), "url": s.get("uri")} for s in srcs]}
