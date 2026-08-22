import json
from pathlib import Path

import pytest

from common import (MODES, data_dir, load_itinerary, save_itinerary,
                    validate_chain)


def make_itinerary():
    return {
        "title": "T",
        "region": "Rome, Italy",
        "points": [
            {"id": "p1", "name": "A", "lat": 41.8902, "lon": 12.4922, "photos": []},
            {"id": "p2", "name": "B", "lat": 41.8925, "lon": 12.4853, "photos": []},
            {"id": "p3", "name": "C", "lat": 41.9009, "lon": 12.4833, "photos": []},
        ],
        "legs": [
            {"from": "p1", "to": "p2", "mode": "foot", "via": []},
            {"from": "p2", "to": "p3", "mode": "transit", "note": "Metro B"},
        ],
        "artifact_url": None,
    }


def test_data_dir_prefers_local(tmp_path):
    (tmp_path / "itineraries").mkdir()
    assert data_dir(tmp_path) == tmp_path / "itineraries"


def test_data_dir_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    d = data_dir(tmp_path)
    assert d == tmp_path / "home" / ".wentro" / "itineraries"
    assert d.is_dir()


def test_validate_chain_accepts_valid():
    validate_chain(make_itinerary())


def test_validate_chain_rejects_broken_link():
    data = make_itinerary()
    data["legs"][1]["from"] = "p1"
    with pytest.raises(ValueError, match="chain"):
        validate_chain(data)


def test_validate_chain_rejects_wrong_leg_count():
    data = make_itinerary()
    data["legs"].pop()
    with pytest.raises(ValueError, match="legs"):
        validate_chain(data)


def test_validate_chain_rejects_bad_mode():
    data = make_itinerary()
    data["legs"][0]["mode"] = "teleport"
    with pytest.raises(ValueError, match="mode"):
        validate_chain(data)


def test_validate_chain_rejects_duplicate_ids():
    data = make_itinerary()
    data["points"][2]["id"] = "p1"
    with pytest.raises(ValueError, match="duplicate"):
        validate_chain(data)


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "t.json"
    data = make_itinerary()
    save_itinerary(p, data)
    loaded = load_itinerary(p)
    assert loaded["title"] == "T"
    assert loaded["updated"]  # stamped by save
    raw = json.loads(p.read_text())
    assert raw["points"][0]["name"] == "A"


def test_load_rejects_invalid_file(tmp_path):
    p = tmp_path / "bad.json"
    data = make_itinerary()
    data["legs"][0]["to"] = "nope"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_itinerary(p)
