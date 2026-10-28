import pytest

from aiassistant.ui import icons, widgets


def test_library_has_all_builtin_widgets():
    expected = {"weather", "line_chart", "bar_chart", "stat_cards", "table", "link_list", "file_results", "gauge",
                "donut_chart", "timer", "choices", "checklist", "callout", "code_block", "timeline", "details"}
    assert expected == set(widgets.names())


@pytest.mark.parametrize("name", widgets.names())
def test_examples_validate_against_their_schema(name):
    meta = widgets.load(name)
    assert meta.get("schema"), f"{name} has no JSON schema"
    assert meta["description"] and meta["data_schema"]
    assert widgets.validate_data(name, meta["example"]) is None


def test_schema_errors_are_specific():
    assert "'value' is a required property" in widgets.validate_data("gauge", {"title": "x"})
    assert "bars/0/value" in widgets.validate_data("bar_chart", {"bars": [{"label": "a", "value": "many"}]})
    assert "unknown widget" in widgets.validate_data("nope", {})
    assert "must be a JSON object" in widgets.validate_data("gauge", [1])


def test_load_refuses_path_tricks():
    assert widgets.load("../secrets") is None and widgets.load("") is None and widgets.load(None) is None


def test_catalog_lists_every_widget():
    cat = widgets.catalog()
    for n in widgets.names():
        assert f"- {n}" in cat


def test_every_icon_the_examples_use_is_a_known_name():
    for n in widgets.names():
        text = str(widgets.load(n)["example"])
        for ic in ("wifi", "signal", "folder", "calendar", "globe", "newspaper", "computer", "cpu"):
            if f"'icon': '{ic}'" in text:
                assert ic in icons.NAMES or ic == "drive-harddisk"


def test_icon_table_is_well_formed():
    assert "battery-full" in icons.names() and "wifi" in icons.names()
    for name, candidates in icons.NAMES.items():
        assert candidates and all(c.endswith("-symbolic") for c in candidates), name
