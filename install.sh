#!/usr/bin/env bash
# Installs gnome-ai-assistant for the current user (no root needed). Honours XDG_DATA_HOME / XDG_CONFIG_HOME.
#   ./install.sh [--with-embed] [--no-enable] [--dev] [--python PATH] [--no-venv]
#     --with-embed  also install the local embedding stack (PyTorch, large) for semantic file search
#     --no-enable   do not enable the GNOME extension in gsettings
#     --dev         run from this source tree (PYTHONPATH) instead of installing the package
#     --python P    interpreter to use (with --no-venv) or to create the venv from
#     --no-venv     do not create a virtualenv; use --python (or python3) as is
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPDIR="$DATA/gnome-ai-assistant"
UUID="ai-assistant@aiassistant.github.io"
WITH_EMBED=0; ENABLE=1; DEV=0; NO_VENV=0; PY="python3"
while [ $# -gt 0 ]; do
  case "$1" in
    --with-embed) WITH_EMBED=1;; --no-enable) ENABLE=0;; --dev) DEV=1;; --no-venv) NO_VENV=1;;
    --python) PY="$2"; shift;;
    -h|--help) sed -n '2,9p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac; shift
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m !  %s\033[0m\n' "$*"; }

say "Checking requirements"
"$PY" - <<'PYEOF' || { echo "Python 3.10+ with PyGObject, GTK 4 and libadwaita is required (apt: python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)." >&2; exit 1; }
import sys
assert sys.version_info >= (3, 10), "Python 3.10+ needed"
import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
PYEOF
command -v glib-compile-schemas >/dev/null || { echo "glib-compile-schemas not found (package libglib2.0-bin)." >&2; exit 1; }
command -v pw-record >/dev/null || warn "pw-record (pipewire-bin) not found: voice input will be unavailable."
command -v bwrap >/dev/null || warn "bubblewrap (bwrap) not found: the optional Antigravity fallback will stay disabled."
command -v pdftotext >/dev/null || warn "pdftotext (poppler-utils) not found: PDFs will not be indexed."

# ---- python environment ----
if [ "$NO_VENV" = 1 ]; then
  PYBIN="$(command -v "$PY")"
  if [ "$DEV" = 0 ]; then
    say "Installing the package into $PYBIN"
    "$PYBIN" -m pip install --quiet "$HERE"
  fi
else
  say "Creating the virtualenv in $APPDIR/venv"
  mkdir -p "$APPDIR"
  "$PY" -m venv --system-site-packages "$APPDIR/venv"   # system site packages: PyGObject comes from the distro
  PYBIN="$APPDIR/venv/bin/python"
  if [ "$DEV" = 0 ]; then
    say "Installing the package"
    EXTRAS=""; [ "$WITH_EMBED" = 1 ] && EXTRAS="[embed]"
    "$PYBIN" -m pip install --quiet --upgrade pip
    "$PYBIN" -m pip install --quiet "$HERE$EXTRAS"
  else
    "$PYBIN" -m pip install --quiet numpy pillow websockets jsonschema
    [ "$WITH_EMBED" = 1 ] && "$PYBIN" -m pip install --quiet sentence-transformers torch torchvision av
  fi
fi
if [ "$DEV" = 1 ]; then EXEC="env PYTHONPATH=$HERE $PYBIN -m aiassistant service"; CLI="env PYTHONPATH=$HERE $PYBIN -m aiassistant"
else EXEC="$PYBIN -m aiassistant service"; CLI="$PYBIN -m aiassistant"; fi

# ---- D-Bus service, desktop entry and overview search provider ----
say "Registering the background service and the GNOME overview search provider"
mkdir -p "$DATA/dbus-1/services" "$DATA/applications" "$DATA/gnome-shell/search-providers"
sed "s|@EXEC@|$EXEC|g" "$HERE/aiassistant/data/dbus/io.github.aiassistant.Service.service.in" \
  > "$DATA/dbus-1/services/io.github.aiassistant.Service.service"
sed "s|@CHAT@|$CLI chat|g" "$HERE/aiassistant/data/dbus/io.github.aiassistant.Service.desktop.in" \
  > "$DATA/applications/io.github.aiassistant.Service.desktop"
sed "s|@WINDOW@|$CLI window|g" "$HERE/aiassistant/data/dbus/io.github.aiassistant.Chat.desktop.in" \
  > "$DATA/applications/io.github.aiassistant.Chat.desktop"
cp "$HERE/aiassistant/data/dbus/io.github.aiassistant.Service.search-provider.ini" "$DATA/gnome-shell/search-providers/"

# ---- extension ----
say "Installing the GNOME Shell extension"
EXT="$DATA/gnome-shell/extensions/$UUID"
rm -rf "$EXT"; mkdir -p "$(dirname "$EXT")"
cp -r "$HERE/extension/$UUID" "$EXT"
rm -f "$EXT/schemas/gschemas.compiled"
glib-compile-schemas "$EXT/schemas"
if [ "$ENABLE" = 1 ] && command -v gsettings >/dev/null && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  "$PY" - "$UUID" <<'PYEOF'
import ast, subprocess, sys
uuid = sys.argv[1]
cur = ast.literal_eval(subprocess.check_output(["gsettings", "get", "org.gnome.shell", "enabled-extensions"]).decode().strip().replace("@as ", ""))
if uuid not in cur:
    subprocess.check_call(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(cur + [uuid])])
    print("   enabled", uuid)
PYEOF
fi

# ---- a launcher on PATH ----
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\nexec %s "$@"\n' "$CLI" > "$HOME/.local/bin/aiassistant"
chmod +x "$HOME/.local/bin/aiassistant"

say "Done. Next steps"
cat <<EOT
  1. Set your Gemini API key (free at https://aistudio.google.com/apikey):   aiassistant config key
  2. Log out and back in once (GNOME Shell loads new extensions and search providers at login).
  3. Press Super + / to open the assistant, or press Super and type three words to search your files.
  4. Check everything any time with:   aiassistant doctor
  Semantic file search needs a one-time index:   aiassistant index   (see README for GPU/Colab)
EOT
