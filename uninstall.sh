#!/usr/bin/env bash
# Removes gnome-ai-assistant for the current user. Keeps your config and index unless --purge is given.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"; CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
UUID="ai-assistant@aiassistant.github.io"
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1
if command -v gsettings >/dev/null && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  python3 - "$UUID" <<'PYEOF' || true
import ast, subprocess, sys
cur = ast.literal_eval(subprocess.check_output(["gsettings", "get", "org.gnome.shell", "enabled-extensions"]).decode().strip().replace("@as ", ""))
if sys.argv[1] in cur:
    cur.remove(sys.argv[1]); subprocess.check_call(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(cur)])
PYEOF
fi
rm -rf "$DATA/gnome-shell/extensions/$UUID"
rm -f "$DATA/dbus-1/services/io.github.aiassistant.Service.service" "$DATA/applications/io.github.aiassistant.Service.desktop" "$DATA/applications/io.github.aiassistant.Chat.desktop" \
      "$DATA/gnome-shell/search-providers/io.github.aiassistant.Service.search-provider.ini" "$HOME/.local/bin/aiassistant"
gdbus call --session --dest io.github.aiassistant.Service --object-path /io/github/aiassistant/Control \
  --method io.github.aiassistant.Control.Quit >/dev/null 2>&1 || true
rm -rf "$DATA/gnome-ai-assistant/venv"
if [ "$PURGE" = 1 ]; then rm -rf "$DATA/gnome-ai-assistant" "$CONF/gnome-ai-assistant" "${XDG_CACHE_HOME:-$HOME/.cache}/gnome-ai-assistant"; echo "purged all data, config and cache"
else echo "kept your index/widgets in $DATA/gnome-ai-assistant and config in $CONF/gnome-ai-assistant (use --purge to delete)"; fi
echo "Removed. Log out and in to unload the extension and search provider."
