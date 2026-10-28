# Privacy

gnome-ai-assistant runs on your computer, but the AI features call Google services. This page lists exactly what leaves
your machine and when. Nothing is sent unless you use the corresponding feature, and there is no telemetry.

## What is sent to Google (Gemini API, using your own API key)

| Feature | Data sent | When |
|---|---|---|
| Chat | your messages, the conversation so far (last ~14 turns), tool results the assistant requested | every chat message |
| Tool results | weather data, web search results, file *snippets*, device facts (see below) | only if the assistant calls that tool to answer you |
| Web search | the search query (Gemini Search grounding) | when you ask something that needs the web |
| `ask` / file questions | up to 12 text snippets (700 characters each) from your indexed notes, and your question | when you use `ask ...` or the assistant searches your files |
| Query rewrite | your search words (to fix typos / translate) | each semantic search when a key is configured |
| Voice input | your microphone audio, streamed to the Gemini Live API | only while the microphone button is recording (captured by `pw-record` inside the service, not by a browser) |

**Never sent:** your file *contents* beyond the snippets above, image or video files (images are only embedded locally or in
your own Colab run), your Gemini key (it stays in `~/.config/gnome-ai-assistant/gemini_key`, mode 600), widget code you did not ask for.

## Device information

The assistant can read, **read-only**: Wi-Fi name and signal, nearby Wi-Fi names, local network addresses, battery, memory,
disk, CPU, temperatures, uptime, OS/kernel, display brightness, audio volume, Bluetooth device *names*, time zone, and the top
processes by CPU (names only). It never returns MAC addresses or full command lines, and cannot change anything. These facts go
to the AI provider only when you ask a question that needs them. Location is derived from your time zone only.

## Antigravity fallback (optional)

If enabled (`provider: auto` and the `agy` CLI is installed), when the Gemini API quota is used up your messages and tool results
are sent through the Antigravity CLI instead, under your own Antigravity account. It runs in a sandbox that hides your home
directory. Set `"provider": "api"` to disable it.

## Local data

- The semantic index (`~/.local/share/gnome-ai-assistant/index.db`) contains text from your documents and vectors; keep it
  private. Delete it any time (`./uninstall.sh --purge`).
- The chat history lives in memory in the background service and is discarded when it exits (after 30 idle minutes) or on "New chat".
- The chat server listens on `127.0.0.1` only and requires a random per-run token; the token file is mode 600 in `$XDG_RUNTIME_DIR`.

## Colab indexing (optional)

`aiassistant index --export` packs document text and downscaled images/video frames into a zip that **you** upload to Google
Colab for GPU embedding. Disconnect and delete the Colab runtime afterwards.

Google's handling of API data is governed by Google's terms for the Gemini API; free-tier data may be used to improve Google
products. Review those terms for your account.
