import json

import pytest

from aiassistant import cli, config


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert "0.1.0" in capsys.readouterr().out


def test_config_show_and_set(capsys):
    cli.main(["config", "set", "provider", '"api"'])
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert '"provider": "api"' in out and "gemini key: NOT set" in out
    assert config.get("provider") == "api"


def test_config_set_accepts_json_lists(capsys):
    cli.main(["config", "set", "index_roots", '["~/Notes"]'])
    assert config.get("index_roots") == ["~/Notes"]


def test_widgets_list(capsys):
    cli.main(["widgets", "list"])
    out = capsys.readouterr().out
    assert "weather" in out and "gauge" in out


def test_widgets_check_passes_for_the_shipped_library(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["widgets", "check"])
    assert e.value.code == 0 and "PROBLEM" not in capsys.readouterr().out
