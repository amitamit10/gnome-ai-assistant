# Architecture

## Processes

1. **GNOME Shell + extension** (`extension/ai-assistant@aiassistant.github.io`): a top-bar button and the shortcut. To open the
   chat it calls `io.github.aiassistant.Control.Open()` on the session bus, which D-Bus-activates the service if needed. It
   then finds the window by its exact title ("AI Assistant"), positions it, and closes it on click-away. It never spawns processes.
2. **Service** (`aiassistant/service.py`): one Python process owning `io.github.aiassistant.Service`. Objects:
   `/io/github/aiassistant/Search` (`org.gnome.Shell.SearchProvider2`) and `/io/github/aiassistant/Control`:
   `Open`, `Ask(text)` (returns at once), `History`, `Reset`, `OpenFile`, `SttStart`/`SttStop`, `Status`, `Quit`, and the signals
   `Progress(text)` and `Reply(json)`. It owns the conversation (`session.py`) and the microphone (`mic.py`) and exits after
   30 idle minutes (D-Bus activation restarts it). `Open()` starts the window process.
3. **Chat window** (`aiassistant window`, `native/app.py`): a single-instance `Adw.Application` (`io.github.aiassistant.Chat`). It
   imports only GTK, cairo and the small helpers, never the search or embedding code, so it starts quickly. It calls the
   service asynchronously and draws replies; closing it loses nothing, because the service keeps the conversation and a new
   window reloads it with `History()`.

## Python package (`aiassistant/`)

| module | role |
|---|---|
| `paths.py`, `config.py` | XDG locations, JSON config, API key |
| `llm/gemini.py` | REST client, model fallback with cooldowns, retries, error types (`QuotaExhausted`, `NoKey`) |
| `llm/agy.py` | sandboxed Antigravity CLI session |
| `agent.py` | system prompt, tool loop, provider fallback, reply assembly |
| `session.py` | the conversation: runs a turn in a thread and reports progress and the reply |
| `tools/registry.py` | tool declarations, dispatch, automatic widgets |
| `tools/{weather,web,files,device}.py` | the tools themselves |
| `ui/widgets.py`, `data/library/*.json` | widget descriptions, data schemas, examples, validation |
| `ui/icons.py` | icon names the model may use and the theme icons they map to |
| `native/app.py` | the GTK window: message list, input, microphone button, D-Bus client |
| `native/widgets.py`, `native/charts.py` | one native builder per widget; Cairo charts |
| `native/markup.py`, `native/icons.py`, `native/style.*` | markdown subset to Pango, icon lookup, small stylesheet |
| `search/{index,embed,query,provider,ask}.py` | indexing, embedding model, in-memory search, overview provider logic |
| `stt.py`, `mic.py` | Gemini Live transcription session; `pw-record` capture |
| `doctor.py`, `cli.py` | diagnostics and the `aiassistant` command |

## A chat turn

1. The window calls `Ask(text)`; the service starts the turn in a thread (`Session.ask`) and returns immediately.
2. `Chat._ask_api`: Gemini `generateContent` with the system prompt (including the widget catalogue) and function declarations.
3. Tool calls run through `registry.call`; tools may queue widgets in a per-question `Context` (each `{widget, data, row}`,
   validated against the widget's JSON Schema).
4. The final text is split into message and `FOLLOWUPS`. The service emits `Progress` signals along the way and a `Reply`
   signal with `{text, widgets, followups, model}` at the end; the window builds native widgets from it.
5. If every Gemini model is out of quota and the provider mode allows, `_ask_agy` runs the same tools through a JSON protocol
   over the sandboxed Antigravity CLI.

## Widgets

A widget is a JSON file (description, one-line data schema for the model, JSON Schema, example) plus a builder function in
`native/widgets.py` that turns the data into a `Gtk.Widget`. Charts are `Gtk.DrawingArea`s drawn with Cairo, coloured from the
live theme's named colours. Same-row widgets are laid out side by side.

## Search

Vectors (float32, L2-normalised) live in SQLite next to the text chunk or media label. `Searcher` loads them into one numpy
matrix, loads the embedding model on demand, and unloads it after 15 idle minutes. Scores are cosine similarities and are **not
calibrated** across queries, which is why the overview provider only answers deliberate queries (a trigger or 3+ words).
