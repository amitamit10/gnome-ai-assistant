# Security model

## Threat model

The assistant reads untrusted text (web pages via search, file contents, tool output). The design assumes **prompt injection
will happen** and limits what it can reach. The model never produces UI code: it chooses a widget by name and supplies data.

| Risk | Mitigation |
|---|---|
| Model-written UI code | There is none. Widgets are a fixed set of native GTK builders; the model supplies JSON data that is validated against a JSON Schema first. Chat text is escaped before the small markdown subset is turned into Pango markup, and only `http(s)` links are clickable. |
| Opening arbitrary files | The service's `OpenFile` only opens files under your configured index roots, of indexable types, outside hidden directories, after resolving symlinks and `..`. Opening is delegated to `xdg-open`. |
| Other local programs talking to the service | The service lives on your session D-Bus (per-user, not reachable from other users or the network). There is no HTTP server or open port. |
| The model running device commands | Every device topic is a fixed read of `/proc`, `/sys` or one fixed command (argv list, no shell); the model supplies only a topic name from an enum. |
| Prompt-injected agent with shell access (Antigravity fallback) | `agy` is an autonomous agent. It runs only inside bubblewrap with a read-only system, an empty tmpfs home (plus its own `~/.gemini`), a scratch directory, an empty `/run` (no session/system bus, ssh or gpg agent sockets), a rebuilt allowlisted environment (no API keys, no D-Bus/display variables) and separate pid, ipc and uts namespaces. `aiassistant doctor --deep` checks the isolation with a canary file. |
| Key exposure | Read from `GEMINI_API_KEY` or a mode-600 file; never logged, never sent to the page. |

## Known limits

- The Antigravity sandbox still has network access (it needs it), so a prompt-injected agent can send data it can read to the internet; abstract unix sockets are not hidden (only a network namespace would). It can reach its own stored login in `~/.gemini`.
- `ai cmd` risk levels and the secret scrubber are pattern based: they catch common shapes, not every possible one. Nothing runs without your confirmation, and `ai explain` prints the scrubbed text it sends.
- Any program running as you can call the service on your session bus (as with every session D-Bus service); it can ask questions
  (using your Gemini quota) and read the conversation. There is no authentication beyond the bus.

## Reporting

Please open a private security advisory on the repository, or email the maintainers. Do not post exploits in public issues.
