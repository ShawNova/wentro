"""Shared helpers for Wentro scripts: data directory, itinerary IO, geo math."""
import json
import os
from datetime import date
from pathlib import Path

USER_AGENT = "wentro/0.1 (+https://github.com/ShawNova/wentro)"
MODES = {"foot", "bike", "car", "transit"}


def data_dir(cwd=None):
    """Resolve the itinerary data directory.

    `./itineraries/` in the working directory if it exists (working inside
    the repo), else `~/.wentro/itineraries/` (created on first use).
    """
    cwd = Path(cwd or os.getcwd())
    local = cwd / "itineraries"
    if local.is_dir():
        return local
    home = Path.home() / ".wentro" / "itineraries"
    home.mkdir(parents=True, exist_ok=True)
    return home


def validate_chain(data):
    """Enforce the chain invariant: legs[i] joins points[i] -> points[i+1]."""
    points = data.get("points", [])
    legs = data.get("legs", [])
    if len(points) < 2:
        raise ValueError("itinerary needs at least 2 points")
    ids = [p["id"] for p in points]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate point ids")
    if len(legs) != len(points) - 1:
        raise ValueError(f"expected {len(points) - 1} legs, got {len(legs)}")
    for i, leg in enumerate(legs):
        if leg["from"] != ids[i] or leg["to"] != ids[i + 1]:
            raise ValueError(
                f"leg {i} breaks the chain: {leg['from']}->{leg['to']}, "
                f"expected {ids[i]}->{ids[i + 1]}"
            )
        if leg["mode"] not in MODES:
            raise ValueError(f"leg {i} has unknown mode {leg['mode']!r}")


def load_itinerary(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_chain(data)
    return data


def save_itinerary(path, data):
    validate_chain(data)
    data["updated"] = date.today().isoformat()
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
