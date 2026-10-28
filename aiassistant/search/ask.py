"""Answer a question from the user's own notes: retrieve the best chunks, let Gemini answer from them only."""
import os

from ..llm import gemini
from . import query


def answer(question, n=12):
    """Returns (answer_text, [source paths]) or None. Sends only the retrieved snippets to Gemini."""
    cands = query.shared().text_candidates(question, n)
    if not cands:
        return None
    lines = "\n".join(f"[{i}] {os.path.basename(p)}: {s[:700]}" for i, p, s in cands)
    r = gemini.json_call("Answer the question using ONLY these snippets from the user's files. Be brief (one or two sentences). "
                         "If they do not contain the answer, say so. Return JSON {\"answer\": str, \"sources\": [ids of the "
                         f"snippets used, best first]}}.\nQuestion: {question!r}\n{lines}", timeout=45)
    if not isinstance(r, dict) or not isinstance(r.get("answer"), str):
        return None
    by_id = {i: p for i, p, _ in cands}
    srcs = [by_id[i] for i in r.get("sources", []) if i in by_id] or [cands[0][1]]
    return r["answer"].strip(), srcs
