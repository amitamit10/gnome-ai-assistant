# Changelog

## 0.1.0 (unreleased)
- Native GTK 4 / libadwaita chat window (no browser, no web server); the conversation and microphone live in the D-Bus service
- Chat window with generative UI: 16 built-in native widgets (weather, gauge, donut, line/bar charts, tables, timer, checklist,
  quick replies, file grid, callout, code block, timeline, details, stat cards, link list)
- Automatic widgets for weather, file search, device info and web sources; follow-up suggestions; skeleton loaders
- Widgets can talk back to the chat (send, open file, copy, open link)
- JSON Schema validation of widget data with precise errors; the model cannot generate widget code
- GNOME overview semantic search (images, documents, video frames) and `ask` answers from your notes
- Voice input with Gemini Live transcription; read-only device information
- Gemini model fallback with hedged requests, cooldowns and retries; hardened bubblewrap sandbox for the Antigravity fallback (no bus by default, optional keyring-only filtered bus, allowlisted environment, own session)
- Extension talks to the service over D-Bus (no process spawning) and has a preferences window
- Installer/uninstaller, `aiassistant doctor`, 240+ automated tests
