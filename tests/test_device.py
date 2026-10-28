import json
import re

import pytest

from aiassistant.tools import device

MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)


@pytest.mark.parametrize("topic", list(device.TOPICS) + ["summary"])
def test_every_topic_returns_json_without_mac_addresses(topic):
    r = device.get(topic)
    assert isinstance(r, dict)
    assert not MAC.search(json.dumps(r)), "MAC addresses must never be returned"


def test_unknown_topic_lists_the_valid_ones():
    r = device.get("rm -rf /")
    assert "error" in r and "wifi" in r["error"]


def test_nmcli_escaped_colons_in_ssid(monkeypatch):
    monkeypatch.setattr(device, "_run", lambda argv, timeout=5: "yes:My\\:Net:77:WPA2:36:130 Mbit/s\n" if "list" in argv else "enabled")
    r = device.wifi()
    assert r["ssid"] == "My:Net" and r["signal_pct"] == 77 and r["connected"]


def test_wifi_disconnected(monkeypatch):
    monkeypatch.setattr(device, "_run", lambda argv, timeout=5: "no:Other:40:WPA2:1:54 Mbit/s\n" if "list" in argv else "enabled")
    assert device.wifi()["connected"] is False


def test_only_fixed_commands_are_ever_run(monkeypatch):
    seen = []
    monkeypatch.setattr(device.subprocess, "run", lambda argv, **k: seen.append(argv) or type("R", (), {"stdout": "", "returncode": 0})())
    for t in device.TOPICS:
        device.get(t)
    allowed = {"nmcli", "ip", "sensors", "gnome-shell", "gsettings", "wpctl", "bluetoothctl", "timedatectl", "ps"}
    assert all(isinstance(a, list) and a[0] in allowed for a in seen), {a[0] for a in seen} - allowed
