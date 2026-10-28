"""Widget library: ready-made, data-driven components. This module holds their descriptions and data contracts.

Each widget is a JSON file in data/library/ with `description`, `data_schema` (one line the model reads), `schema` (JSON
Schema used to validate the model's data before anything is drawn) and `example`. The drawing itself is native GTK code in
aiassistant/native/widgets.py, one builder per widget name, so a widget needs both a JSON file and a builder.
"""
import json
import re

from .. import paths

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


def _dir():
    return paths.BUNDLED / "library"


def load(name):
    """The widget's metadata dict, or None."""
    if not NAME_RE.match(name or ""):
        return None
    p = _dir() / f"{name}.json"
    return json.loads(p.read_text(encoding="utf8")) if p.is_file() else None


def names():
    return [f.stem for f in sorted(_dir().glob("*.json"))]


def catalog():
    """One line per widget for the system prompt."""
    return "\n".join(f"- {n}: {load(n).get('description', '')} data = {load(n).get('data_schema', '')}" for n in names())


def validate_data(name, data):
    """None if OK, else a short message the model can act on."""
    meta = load(name)
    if not meta:
        return f"unknown widget '{name}'. Available: {', '.join(names())}"
    if not isinstance(data, dict):
        return f"data for '{name}' must be a JSON object matching: {meta.get('data_schema', '')}"
    schema = meta.get("schema")
    if schema:
        try:
            import jsonschema
            err = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema).iter_errors(data))
        except Exception:
            return None  # a broken schema must never block rendering
        if err:
            where = "/".join(str(p) for p in err.absolute_path) or "(top level)"
            return f"invalid data for '{name}' at {where}: {err.message[:160]}. Expected: {meta.get('data_schema', '')}"
    return None
