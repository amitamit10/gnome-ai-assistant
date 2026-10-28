"""The native GTK window. Anything that needs a display runs in a subprocess under Xvfb (skipped when it is not installed)."""
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
needs_gtk = pytest.mark.skipif(subprocess.run([sys.executable, "-c", "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')"],
                                              capture_output=True).returncode != 0, reason="GTK 4 / libadwaita not available")


def pango(text):
    import gi
    gi.require_version("GLib", "2.0")
    from aiassistant.native import markup
    return markup.to_pango(text)


@needs_gtk
def test_markdown_subset_is_converted_and_escaped():
    out = pango("Hello **bold** and *it* with `code` & <b>x</b> [link](https://a.b/c)\n- one\n1. two")
    assert "<b>bold</b>" in out and "<i>it</i>" in out and "<tt>code</tt>" in out
    assert "&amp;" in out and "&lt;b&gt;x&lt;/b&gt;" in out, "model text must never inject markup"
    assert '<a href="https://a.b/c">link</a>' in out and "•  one" in out and "1.  two" in out


@needs_gtk
def test_only_http_links_become_links_and_code_is_protected():
    out = pango("[bad](javascript:alert(1)) and `**not bold**`")
    assert "<a href" not in out and "<tt>**not bold**</tt>" in out


def test_every_widget_has_a_native_builder():
    from aiassistant.ui import widgets
    r = subprocess.run([sys.executable, "-c",
                        "import gi; gi.require_version('Gtk','4.0')\n"
                        "from aiassistant.native import widgets as n\n"
                        "from aiassistant.ui import widgets as u\n"
                        "print(sorted(set(u.names()) ^ set(n.BUILDERS)))"], capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and r.stdout.strip() == "[]", r.stdout + r.stderr


@needs_gtk
@pytest.mark.skipif(not shutil.which("xvfb-run"), reason="xvfb-run not installed")
def test_every_widget_renders_with_a_sane_size(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "GDK_BACKEND": "x11"}
    r = subprocess.run(["xvfb-run", "-a", sys.executable, str(ROOT / "tests" / "render_widgets.py"), str(tmp_path)],
                       capture_output=True, text=True, env=env, timeout=240)
    assert r.returncode == 0, r.stderr[-800:]
    sizes = json.loads(r.stdout.strip().splitlines()[-1])
    from aiassistant.ui import widgets
    assert set(sizes) == set(widgets.names())
    for name, (w, h) in sizes.items():
        assert 600 <= w <= 700 and 40 <= h <= 420, f"{name} rendered {w}x{h}"
        png = (tmp_path / f"{name}.png").read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1500, f"{name}.png looks empty"
        assert struct.unpack(">II", png[16:24]) == (w, h)
