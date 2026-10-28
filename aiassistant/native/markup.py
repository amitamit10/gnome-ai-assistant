"""Tiny markdown subset -> Pango markup for chat text. Everything is escaped first, so model or web text can never inject markup."""
import re

from gi.repository import GLib

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITAL = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])")
_CODE = re.compile(r"`([^`\n]+)`")
_BARE = re.compile(r"(?<![\"'>=])\b(https?://[^\s<)]+[^\s<).,;:!?])")


def _inline(text):
    esc = GLib.markup_escape_text(text)
    codes = []

    def stash(m):  # code spans are protected from the other rules
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    esc = _CODE.sub(stash, esc)
    esc = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', esc)
    esc = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", esc)
    esc = _ITAL.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", esc)
    esc = _BARE.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', esc)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<tt>{codes[int(m.group(1))]}</tt>", esc)


def to_pango(text):
    out, in_fence = [], False
    for line in (text or "").strip().splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(f"<tt>{GLib.markup_escape_text(line)}</tt>")
            continue
        m = re.match(r"^\s*(#{1,6})\s+(.*)$", line)
        if m:
            out.append(f"<b>{_inline(m.group(2))}</b>")
            continue
        m = re.match(r"^(\s*)[-*•]\s+(.*)$", line)
        if m:
            out.append(f"{'    ' if len(m.group(1)) >= 2 else ''}•  {_inline(m.group(2))}")
            continue
        m = re.match(r"^\s*(\d+)[.)]\s+(.*)$", line)
        if m:
            out.append(f"{m.group(1)}.  {_inline(m.group(2))}")
            continue
        out.append(_inline(line))
    return "\n".join(out)
