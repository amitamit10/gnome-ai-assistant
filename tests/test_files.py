import os

from aiassistant import config
from aiassistant.tools import files


def _setup(tmp_path):
    root = tmp_path / "home" / "Documents"
    (root / ".secret").mkdir(parents=True)
    (root / "sub").mkdir()
    (root / "note.md").write_text("hi")
    (root / "sub" / "pic.png").write_bytes(b"x")
    (root / ".secret" / "key.md").write_text("no")
    (root / "run.sh").write_text("echo")
    (tmp_path / "home" / "other.md").write_text("outside")
    config.save({"index_roots": [str(root)]})
    return root


def test_open_is_limited_to_indexed_files(tmp_path):
    root = _setup(tmp_path)
    assert files.allowed(str(root / "note.md")) and files.allowed(str(root / "sub" / "pic.png"))
    assert not files.allowed(str(root / ".secret" / "key.md")), "hidden folders are never opened"
    assert not files.allowed(str(root / "run.sh")), "only indexable file types"
    assert not files.allowed(str(tmp_path / "home" / "other.md")), "outside the index roots"
    assert not files.allowed("/etc/passwd")
    assert not files.allowed(str(root / ".." / "other.md")), "path traversal"
    assert not files.allowed(str(root / "missing.md"))


def test_symlink_escape_is_blocked(tmp_path):
    root = _setup(tmp_path)
    os.symlink(tmp_path / "home" / "other.md", root / "link.md")
    assert not files.allowed(str(root / "link.md"))


def test_open_file_launches_xdg_open_only_when_allowed(tmp_path, monkeypatch):
    root = _setup(tmp_path)
    launched = []
    monkeypatch.setattr(files.subprocess, "Popen", lambda argv, **k: launched.append(argv))
    assert files.open_file(str(root / "note.md")) and launched[0][0] == "xdg-open"
    assert not files.open_file("/etc/passwd") and len(launched) == 1


def test_short_paths(tmp_path):
    assert files.short(files.HOME + "/x") == "~/x"


def test_thumbnail_is_a_small_data_uri(tmp_path):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGB", (1600, 1200), (200, 10, 10)).save(p)
    uri = files.thumbnail(str(p))
    assert uri.startswith("data:image/jpeg;base64,") and len(uri) < 20000
    assert files.thumbnail(str(tmp_path / "nope.png")) is None
