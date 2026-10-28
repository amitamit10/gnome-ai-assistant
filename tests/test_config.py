import json

from aiassistant import config, paths


def test_paths_follow_xdg(sandbox):
    assert str(paths.config_dir()).startswith(str(sandbox / "config"))
    assert str(paths.data_dir()).startswith(str(sandbox / "data"))
    assert str(paths.index_db()).startswith(str(sandbox / "data"))


def test_defaults_and_overrides():
    assert config.get("provider") == "auto"
    config.save({"provider": "api", "stt_model": "x"})
    assert config.get("provider") == "api" and config.get("stt_model") == "x"
    assert config.get("agy_model")  # untouched defaults remain


def test_key_from_env_and_file(monkeypatch):
    assert config.gemini_key() is None
    paths.ensure(paths.config_dir(), 0o700)
    paths.key_file().write_text("file-key\n")
    assert config.gemini_key() == "file-key"
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    assert config.gemini_key() == "env-key"


def test_corrupt_config_falls_back_to_defaults():
    paths.ensure(paths.config_dir())
    paths.config_file().write_text("{not json")
    assert config.get("provider") == "auto"


def test_expand_roots(sandbox):
    config.save({"index_roots": ["~/Notes"]})
    assert config.expand_roots() == [str(sandbox / "home" / "Notes")]
