# gnome-ai-assistant

An AI assistant built into the GNOME desktop, for GNOME 46 on Wayland or X11 (tested on Zorin OS 18).

- **A native chat window with generative UI.** Press **Super + /** and ask. The window is a real GTK 4 / libadwaita
  application, so it opens fast and looks like the rest of your desktop. Answers can include live widgets: weather cards,
  gauges, charts, tables, timers, checklists, file grids, quick-reply buttons. Widgets are ready-made native components; the
  assistant picks one and fills in validated data, so nothing is generated or rendered twice.
- **Semantic search in the GNOME overview.** Press **Super** and type three words (`screenshots of the settings menu`) to
  find documents, images and video moments *by meaning*. `ask what caused the outage` answers from your own notes.
- **Voice input.** Click the microphone and speak (Gemini Live transcription).
- **Read-only device info.** "How is my battery / wifi / disk?" with live gauges. Nothing can be changed.
- **Follows your desktop.** It is a normal GTK 4 app: your theme, accent colour, font, light/dark mode and icon theme apply.

> **Status: 0.1.0, early.** Developed on one machine. Read [Limits and caveats](#limits-and-caveats) before relying on it.

## How it fits together

```
 GNOME Shell                       background service (Python, D-Bus activated, exits when idle)
┌───────────────────────┐ Open()  ┌────────────────────────────────────────────────────────┐
│ extension (JavaScript)│────────▶│ io.github.aiassistant.Service                           │
│  top-bar button,      │ D-Bus   │  ├─ SearchProvider2 → GNOME overview results             │
│  Super+/ , placement  │         │  └─ Control: Open Ask History Reset Stt* + Progress/Reply│
└───────────────────────┘         │       agent: Gemini tools loop, Antigravity fallback     │
        ▲ finds the window        │       tools: weather, web, files, device, widgets        │
        │ by its exact title      │       owns the conversation and the microphone           │
   GTK 4 / libadwaita window ◀────┴──── D-Bus (Ask, signals) ───────────────────────────────┘
   (aiassistant window, its own process)
```

The extension is deliberately thin: it asks the service to open the chat over D-Bus (no processes are spawned), then places
and dismisses the window. The window is a separate light process that only draws; the conversation lives in the service, so
closing and reopening the window loses nothing. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- GNOME Shell 46, Python 3.10+, **python3-gi** with **gir1.2-gtk-4.0** and **gir1.2-adw-1** (libadwaita 1.5+),
  `libglib2.0-bin` (for `glib-compile-schemas`)
- Optional: `pipewire-bin` (`pw-record`) for voice input
- A **Gemini API key** (free: <https://aistudio.google.com/apikey>) for chat, voice and web search
- Optional: `poppler-utils` (index PDFs), `bubblewrap` + the Antigravity CLI (`agy`) for the fallback provider
- Optional, for semantic file search: PyTorch and sentence-transformers (several GB), see [Semantic search](#semantic-search)

## Install

```bash
git clone <this repository> gnome-ai-assistant && cd gnome-ai-assistant
./install.sh                 # add --with-embed to also install the local embedding stack
aiassistant config key       # paste your Gemini API key (hidden input)
```

Then **log out and back in once**: GNOME Shell only discovers new extensions and search providers at login. After that:

```bash
aiassistant doctor           # checks everything and tells you how to fix what is wrong
```

Uninstall: `./uninstall.sh` (keeps your index and config; `--purge` deletes them too).

## Using it

| You do | What happens |
|---|---|
| **Super + /** or **Super + \\** | open the chat; press again, or click elsewhere, to close it |
| **Super**, then type 3+ words | semantic file search in the overview |
| **Super**, then `? word` or `ai word` | same, for one or two words |
| **Super**, then `ask your question` | an answer from your notes, with the source files |
| microphone button in the chat | click to start listening, click again to finish; the transcript lands in the input box |
| click a widget (button, file card, checkbox) | widgets are interactive; some talk back to the chat |

Settings: `aiassistant config show`, or the extension's preferences (shortcut, close-on-click-away, top-bar button).

## Semantic search

Index your files once (images, documents, video frames) with a multilingual embedding model:

```bash
./install.sh --with-embed
aiassistant index            # folders come from "index_roots" in the config
aiassistant search "photos of flowers"
```

On a CPU this is **slow** (EmbeddingGemma 2: about 4 text chunks per second and several seconds per image). Options:

1. **GPU on Colab** (free T4): `aiassistant index --export`, run [docs/colab-embed.ipynb](docs/colab-embed.ipynb),
   then `aiassistant index --import vectors.npy`. Thousands of images take minutes.
2. **A smaller text-only model:** `aiassistant config set embed_model '"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"'`
   (fast, no images or video).

Skipped on purpose: hidden folders, `node_modules`/`.git`/build folders, tiny images, files over 20 MB, code and data files.

## The generative UI

Replies can contain widgets. `get_weather`, `search_files`, `get_device_info` and `web_search` attach theirs automatically
(no LLM tokens, instant); for anything else the model picks from the library and fills in data that is validated against a
JSON Schema, so mistakes come back as precise errors it can fix. The library is a fixed set of native GTK widgets: the model
cannot invent new code, which also means a prompt injection cannot make the window run anything.

`aiassistant widgets list` and `aiassistant widgets check` show and verify the library.
To add a widget see [docs/WIDGETS.md](docs/WIDGETS.md).

## Configuration

`~/.config/gnome-ai-assistant/config.json` (all optional):

| key | default | meaning |
|---|---|---|
| `provider` | `"auto"` | `auto`: Gemini API, then sandboxed Antigravity when out of quota; `api`: never Antigravity; `agy`: Antigravity only |
| `models` | 7 Gemini models | tried in order; the free tier allows ~20 requests/day **per model** |
| `agy_model` | `gemini-3.8-flash-low` | model used through the Antigravity CLI |
| `agy_keyring` | `false` | let the sandboxed Antigravity reach your desktop keyring (needed if its login is stored there); exposes every keyring secret to it, see [SECURITY.md](SECURITY.md) |
| `stt_model` | `gemini-3.5-transcribe-live` | live transcription model |
| `index_roots` | Documents, Downloads, Desktop, Pictures, Videos | folders to index |
| `embed_model` | `google/embeddinggemma-2` | embedding model (must match the index) |

All paths follow the XDG directories (`~/.config`, `~/.local/share`, `~/.cache` under `gnome-ai-assistant/`).

## Limits and caveats

- **Gemini free tier is small.** About 20 requests per day per model; a chat message uses 2-3. Enable billing on the key's
  Google Cloud project for regular use, or rely on the Antigravity fallback.
- **Antigravity fallback** is slow (12-15 s per turn) and is an autonomous coding agent, so it only ever runs inside a
  bubblewrap sandbox that hides your home directory; `aiassistant doctor --deep` verifies this with a canary file. Check Google's
  terms before using an automated CLI; set `"provider": "api"` to disable it.
- **Speech-to-text** returns the transcript after you stop speaking (1-2 s), not word by word.
- **Your data goes to Google** for chat, web search, voice and (for `ask`) the snippets used for an answer. See [PRIVACY.md](PRIVACY.md).
- **Location is approximate** (timezone based); there is no GPS or IP lookup.
- Tested on GNOME 46 only. The extension's `shell-version` lists exactly what is declared supported.
- The D-Bus names are placeholders (`io.github.aiassistant.*`); see `aiassistant/constants.py` before publishing under your own.

## Development

```bash
python -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest                         # 240+ tests: widgets (rendered under Xvfb), agent, session, search, installer, extension
```

The extension is tested against stub GNOME APIs with `gjs` (`tests/test_extension.py`); the installer and the real D-Bus
service are tested in a sandbox (`tests/test_install.py`). Everything is redirected with `XDG_*` variables, so tests never
touch your real files.

## License

MIT. Widget icons are your own desktop icon theme's symbolic icons; nothing is bundled.
