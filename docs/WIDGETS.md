# Adding a widget

A widget is two things that share a name:

1. `aiassistant/data/library/<name>.json`: what the model sees and how its data is checked.
2. A builder in `aiassistant/native/widgets.py`: `@builder def w_<name>(data, ctx) -> Gtk.Widget`.

```json
{
  "description": "Single progress bar with a label.",
  "data_schema": "{label, percent}",
  "schema": {"type": "object", "required": ["percent"],
             "properties": {"label": {"type": "string"}, "percent": {"type": "number"}}},
  "example": {"label": "Disk used", "percent": 62}
}
```

```python
@builder
def w_progress(d, ctx):
    bar = Gtk.ProgressBar(fraction=_num(d.get("percent")) / 100)
    return card(d.get("label"), bar)
```

`description` and `data_schema` are what the model reads in its catalogue. `schema` (JSON Schema) is enforced before anything is
drawn, so bad data returns an error the model can fix. `example` is used by `aiassistant widgets check` and the render test.

## Conventions

- Wrap the content in `card(title, ...)` so it matches the other widgets, and use libadwaita style classes (`heading`,
  `dim-label`, `caption`, `title-3`, `monospace`, `pill`, `circular`) instead of your own colours.
- Colours come from the live theme: `charts.named(widget, "accent_color")` (or `success_color`, `warning_color`, `error_color`).
- Icons: `icons.image("wifi", 16)`; names and their theme icon candidates are in `aiassistant/ui/icons.py`.
- Actions available through `ctx`: `ctx.send(text)` (ask the assistant), `ctx.open_file(path)` (indexed files only),
  `ctx.open_url(url)` (http/https), `ctx.copy(text)`.
- Every string from the model is untrusted: use `label(text)` (plain text) rather than markup unless you escape it first.
- Keep it under about 420 px tall and let it fill the width it is given.

## Checking your widget

```bash
aiassistant widgets list
aiassistant widgets check     # every JSON validates its own example and has a builder
python tests/render_widgets.py OUTDIR      # PNG of every widget (needs a display, or run under xvfb-run)
```

`pytest tests/test_native.py` renders every widget under Xvfb and checks the sizes.
