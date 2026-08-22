"""Shared helpers for Wentro scripts: data directory, itinerary IO, geo math."""
import json
import math
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


EARTH_R_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def median_center(latlons):
    lats = sorted(x[0] for x in latlons)
    lons = sorted(x[1] for x in latlons)
    n = len(lats)
    mid = n // 2

    def med(v):
        return v[mid] if n % 2 else (v[mid - 1] + v[mid]) / 2

    return med(lats), med(lons)


def decode_polyline(s, precision=5):
    """Decode a polyline string (Google algorithm) to [(lat, lon), ...]."""
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10 ** precision
    while index < len(s):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(s[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lat / factor, lon / factor))
    return coords


def lonlat_to_global_px(lon, lat, zoom, tile_size=256):
    """Web-Mercator global pixel coordinates at a zoom level."""
    n = tile_size * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y
