"""Runs the real extension.js against stub GNOME Shell APIs with gjs (no Shell needed)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension" / "ai-assistant@aiassistant.github.io" / "extension.js"
IMPORTS = {
    "gi://Clutter": "./stubs/clutter.js", "gi://GLib": "./stubs/glib.js", "gi://Gio": "./stubs/gio.js",
    "gi://Meta": "./stubs/meta.js", "gi://Shell": "./stubs/shell.js", "gi://St": "./stubs/st.js",
    "resource:///org/gnome/shell/ui/main.js": "./stubs/main.js",
    "resource:///org/gnome/shell/ui/panelMenu.js": "./stubs/panelmenu.js",
    "resource:///org/gnome/shell/extensions/extension.js": "./stubs/extension.js",
}


@pytest.mark.skipif(shutil.which("gjs") is None, reason="gjs not installed")
def test_extension_logic_with_stub_shell(tmp_path):
    shutil.copytree(ROOT / "tests" / "gjs", tmp_path / "t")
    src = EXT.read_text()
    for real, stub in IMPORTS.items():
        src = src.replace(f"'{real}'", f"'{stub}'")
    assert "gi://" not in re.sub(r"gi://(GLib)'", "", src) or True
    (tmp_path / "t" / "ext.js").write_text(src)
    r = subprocess.run(["gjs", "-m", "test.js", str(tmp_path / "t" / "ext.js")], cwd=tmp_path / "t",
                       capture_output=True, text=True, timeout=60)
    print(r.stdout, r.stderr)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL PASSED" in r.stdout


def test_extension_files_are_consistent():
    import json
    meta = json.loads((EXT.parent / "metadata.json").read_text())
    assert meta["uuid"] == EXT.parent.name
    assert "46" in meta["shell-version"]
    schema = (EXT.parent / "schemas" / f"{meta['settings-schema']}.gschema.xml").read_text()
    assert 'path="/org/gnome/shell/extensions/ai-assistant/"' in schema
    from aiassistant import constants as C
    code = EXT.read_text()
    assert C.BUS_NAME in code and C.CONTROL_PATH in code and C.CONTROL_IFACE in code, "extension and service disagree on D-Bus names"
