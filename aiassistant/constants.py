"""D-Bus names shared by the service, the extension and the installer.

These are placeholders in the reverse-DNS style; change them together (here, in extension/, and in data/dbus/) if you
publish under your own domain or GitHub name.
"""
import os

# overridable so tests can run their own service next to a real installation without ever touching it
BUS_NAME = os.environ.get("AIASSISTANT_BUS_NAME", "io.github.aiassistant.Service")
SEARCH_PATH = "/io/github/aiassistant/Search"
CONTROL_PATH = "/io/github/aiassistant/Control"
CONTROL_IFACE = "io.github.aiassistant.Control"
SEARCH_IFACE = "org.gnome.Shell.SearchProvider2"
WINDOW_TITLE = "AI Assistant"  # the chat page <title>; the extension finds the window by this exact title
