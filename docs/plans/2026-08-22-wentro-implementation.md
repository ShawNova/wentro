# Wentro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Wentro skill: scripts that geocode a finished trip, fetch real routes, stitch an OSM basemap, and render an interactive HTML artifact plus a static PNG share image, orchestrated by SKILL.md.

**Architecture:** Conversation-side pipeline (CSP forbids network calls in the artifact). Python CLI scripts under `skill/scripts/` do deterministic work (HTTP, math, rendering); Claude per SKILL.md does semantic work (normalization, arbitration) and publishes. `itineraries/<slug>.json` is the source of truth.

**Tech Stack:** Python ≥3.10, requests, Pillow, pytest. External: Nominatim, FOSSGIS OSRM (`routing.openstreetmap.de`), OSM tile server.

## Global Constraints

- Python ≥ 3.10. Third-party runtime deps ONLY `requests` and `Pillow>=10.1` (`requirements.txt`); dev dep `pytest` (`requirements-dev.txt`).
- All code, comments, docstrings, commit messages: English.
- User-Agent everywhere: `wentro/0.1 (+https://github.com/ShawNova/wentro)`.
- Etiquette: Nominatim ≥1 s between requests; tiles sequential with 0.15 s sleep, ≤80 tiles per build; OSRM low volume.
- Rendered page must stay under the 16 MB artifact limit; template contains NO `<!doctype>`, `<html>`, `<head>`, or `<body>` tags (artifact wrapper adds them).
- Commit after every task: `git -c commit.gpgsign=false commit` (1Password signing unavailable in this environment) with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Run tests with `python3 -m pytest` from the repo root.

---

### Task 1: Scaffolding + itinerary IO (`common.py` part A)

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `tests/conftest.py`, `skill/scripts/common.py`, `tests/test_common.py`

**Interfaces:**
- Produces: `common.data_dir(cwd=None) -> Path`; `common.validate_chain(data) -> None` (raises `ValueError`); `common.load_itinerary(path) -> dict`; `common.save_itinerary(path, data) -> None`; constants `common.USER_AGENT: str`, `common.MODES: set[str]` = `{"foot","bike","car","transit"}`.

- [ ] **Step 1: Write dependency files and conftest**

`requirements.txt`:
```
requests>=2.31
Pillow>=10.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
```

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill" / "scripts"))
```

Run: `python3 -m pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests**

`tests/test_common.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_common.py -v`
Expected: FAIL / ERROR with "No module named 'common'"

- [ ] **Step 4: Implement `skill/scripts/common.py` (part A)**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_common.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt tests/ skill/scripts/common.py
git -c commit.gpgsign=false commit -m "feat: itinerary IO, chain validation, data dir resolution

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Geo math (`common.py` part B)

**Files:**
- Modify: `skill/scripts/common.py` (append)
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `haversine_km(lat1, lon1, lat2, lon2) -> float`; `median_center(latlons: list[tuple]) -> tuple[float, float]`; `decode_polyline(s: str, precision=5) -> list[tuple[lat, lon]]`; `lonlat_to_global_px(lon, lat, zoom, tile_size=256) -> tuple[float, float]` (Web-Mercator global pixel coords).

- [ ] **Step 1: Write the failing tests**

`tests/test_geo.py`:
```python
import pytest

from common import (decode_polyline, haversine_km, lonlat_to_global_px,
                    median_center)


def test_haversine_paris_london():
    d = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert 340 < d < 348


def test_haversine_zero():
    assert haversine_km(41.9, 12.5, 41.9, 12.5) == 0


def test_median_center_odd():
    pts = [(0.0, 0.0), (10.0, 10.0), (2.0, 4.0)]
    assert median_center(pts) == (2.0, 4.0)


def test_median_center_even():
    pts = [(0.0, 0.0), (2.0, 4.0)]
    assert median_center(pts) == (1.0, 2.0)


def test_decode_polyline_google_reference_vector():
    # Reference example from the polyline algorithm spec.
    coords = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert coords == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_mercator_origin():
    assert lonlat_to_global_px(0.0, 0.0, 0) == (128.0, 128.0)
    assert lonlat_to_global_px(0.0, 0.0, 1) == (256.0, 256.0)


def test_mercator_dateline():
    x, _ = lonlat_to_global_px(-180.0, 0.0, 0)
    assert x == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_geo.py -v`
Expected: FAIL with ImportError (names not defined)

- [ ] **Step 3: Append implementation to `common.py`**

```python
import math

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
```

(Move the `import math` to the top of the file with the other imports.)

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skill/scripts/common.py tests/test_geo.py
git -c commit.gpgsign=false commit -m "feat: geo math — haversine, median center, polyline decode, mercator

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Coherence validation CLI (`validate.py`)

**Files:**
- Create: `skill/scripts/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `common.load_itinerary`, `common.haversine_km`, `common.median_center`
- Produces: `validate.check(data) -> dict` with keys `ok: bool`, `errors: list[str]`, `warnings: list[str]`; CLI `python3 skill/scripts/validate.py --itinerary <path>` printing that dict as JSON, exit code 0 when ok, 1 when not.

- [ ] **Step 1: Write the failing tests**

`tests/test_validate.py`:
```python
from validate import check


def base():
    return {
        "title": "T",
        "region": "Rome, Italy",
        "points": [
            {"id": "p1", "name": "A", "lat": 41.8902, "lon": 12.4922},
            {"id": "p2", "name": "B", "lat": 41.8925, "lon": 12.4853},
            {"id": "p3", "name": "C", "lat": 41.9009, "lon": 12.4833},
        ],
        "legs": [
            {"from": "p1", "to": "p2", "mode": "foot", "via": []},
            {"from": "p2", "to": "p3", "mode": "foot", "via": []},
        ],
    }


def test_clean_itinerary_passes():
    r = check(base())
    assert r == {"ok": True, "errors": [], "warnings": []}


def test_outlier_is_hard_error():
    data = base()
    # Milan in a Rome walking itinerary: ~475 km away.
    data["points"][2].update(lat=45.4642, lon=9.19)
    r = check(data)
    assert not r["ok"]
    assert any("outlier" in e for e in r["errors"])


def test_outlier_threshold_scales_with_mode():
    data = base()
    data["points"][2].update(lat=45.4642, lon=9.19)
    for leg in data["legs"]:
        leg["mode"] = "car"  # 500 km threshold: Milan is fine by car
    r = check(data)
    assert r["ok"]


def test_long_foot_leg_warns():
    data = base()
    data["points"][1].update(lat=42.05, lon=12.4922)  # ~18 km north
    r = check(data)
    assert r["ok"]  # warning, not error
    assert any("long for mode 'foot'" in w for w in r["warnings"])


def test_two_points_skip_outlier_check():
    data = base()
    data["points"].pop()
    data["legs"].pop()
    assert check(data)["ok"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_validate.py -v`
Expected: FAIL with "No module named 'validate'"

- [ ] **Step 3: Implement `skill/scripts/validate.py`**

```python
"""Coherence checks: outlier points and implausible legs.

Numeric checks live here so they run identically every time
("scripts compute, Claude judges").
"""
import argparse
import json
import sys

from common import haversine_km, load_itinerary, median_center

# Hard-error distance from the itinerary's median center, by the most
# permissive mode present in the trip.
OUTLIER_KM = {"foot": 30, "bike": 100, "car": 500, "transit": 500}
# Per-leg crow-flies distances that trigger a confirmation warning.
LEG_WARN_KM = {"foot": 15, "bike": 60}


def check(data):
    errors, warnings = [], []
    pts = {p["id"]: p for p in data["points"]}
    modes = {leg["mode"] for leg in data["legs"]}
    threshold = max(OUTLIER_KM[m] for m in modes)

    latlons = [(p["lat"], p["lon"]) for p in data["points"]]
    if len(latlons) >= 3:
        center = median_center(latlons)
        for p in data["points"]:
            d = haversine_km(p["lat"], p["lon"], *center)
            if d > threshold:
                errors.append(
                    f"outlier: {p['id']} ({p['name']}) is {d:.0f} km from the "
                    f"itinerary center (threshold {threshold} km)"
                )

    for i, leg in enumerate(data["legs"]):
        a, b = pts[leg["from"]], pts[leg["to"]]
        d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        warn = LEG_WARN_KM.get(leg["mode"])
        if warn and d > warn:
            warnings.append(
                f"leg {i} ({a['name']} -> {b['name']}): {d:.0f} km as the "
                f"crow flies is long for mode '{leg['mode']}'"
            )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--itinerary", required=True)
    args = ap.parse_args()
    report = check(load_itinerary(args.itinerary))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_validate.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skill/scripts/validate.py tests/test_validate.py
git -c commit.gpgsign=false commit -m "feat: coherence validation — outlier hard errors, leg plausibility warnings

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Geocoding CLI (`geocode.py`)

**Files:**
- Create: `skill/scripts/geocode.py`
- Test: `tests/test_geocode.py`

**Interfaces:**
- Consumes: `common.USER_AGENT`
- Produces: `geocode.geocode(query, region=None, limit=5) -> dict` with keys `bounded: bool`, `candidates: list[{display_name, lat, lon, type, importance}]`; `geocode.region_viewbox(region) -> str | None` (`"w,s,e,n"`); `geocode.search(params) -> list` (the only function that touches the network — tests monkeypatch it); CLI `python3 skill/scripts/geocode.py --query Q [--region R] [--limit N]` printing the geocode() dict as JSON.

- [ ] **Step 1: Write the failing tests**

`tests/test_geocode.py`:
```python
import geocode


def fake_search(responses):
    """Return a stub for geocode.search that pops canned responses."""
    calls = []

    def stub(params):
        calls.append(params)
        return responses.pop(0)

    return stub, calls


ROME_REGION_HIT = [{
    "display_name": "Roma, Italia",
    "lat": "41.8933", "lon": "12.4829",
    "boundingbox": ["41.65", "42.14", "12.23", "12.85"],  # s, n, w, e
}]

COLOSSEUM_HIT = [{
    "display_name": "Colosseo, Roma, Italia",
    "lat": "41.8902", "lon": "12.4922",
    "type": "attraction", "importance": 0.9,
}]


def test_region_viewbox_reorders_bbox(monkeypatch):
    stub, _ = fake_search([list(ROME_REGION_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    assert geocode.region_viewbox("Rome, Italy") == "12.23,41.65,12.85,42.14"


def test_bounded_search_used_when_region_resolves(monkeypatch):
    stub, calls = fake_search([list(ROME_REGION_HIT), list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum", region="Rome, Italy")
    assert r["bounded"] is True
    assert r["candidates"][0]["lat"] == 41.8902
    assert calls[1]["bounded"] == 1
    assert calls[1]["viewbox"] == "12.23,41.65,12.85,42.14"


def test_falls_back_to_unbounded_when_bounded_empty(monkeypatch):
    stub, calls = fake_search([list(ROME_REGION_HIT), [], list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum", region="Rome, Italy")
    assert r["bounded"] is False
    assert len(r["candidates"]) == 1
    assert "bounded" not in calls[2]


def test_no_region_goes_straight_unbounded(monkeypatch):
    stub, calls = fake_search([list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum")
    assert r["bounded"] is False
    assert len(calls) == 1


def test_empty_result_reported(monkeypatch):
    stub, _ = fake_search([[], []])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Xyzzynotaplace", region=None)
    assert r["candidates"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_geocode.py -v`
Expected: FAIL with "No module named 'geocode'"

- [ ] **Step 3: Implement `skill/scripts/geocode.py`**

```python
"""Nominatim geocoding with region bias. Max one request per second."""
import argparse
import json
import time

import requests

from common import USER_AGENT

NOMINATIM = "https://nominatim.openstreetmap.org/search"


def search(params):
    """Single Nominatim request. The only network touchpoint in this module."""
    r = requests.get(
        NOMINATIM, params=params, headers={"User-Agent": USER_AGENT}, timeout=30
    )
    r.raise_for_status()
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    return r.json()


def region_viewbox(region):
    """Geocode the region itself; return its bbox as 'w,s,e,n' or None."""
    hits = search({"q": region, "format": "jsonv2", "limit": 1})
    if not hits:
        return None
    s, n, w, e = hits[0]["boundingbox"]
    return f"{w},{s},{e},{n}"


def _fmt(h):
    return {
        "display_name": h["display_name"],
        "lat": float(h["lat"]),
        "lon": float(h["lon"]),
        "type": h.get("type"),
        "importance": h.get("importance"),
    }


def geocode(query, region=None, limit=5):
    base = {"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 1}
    if region:
        vb = region_viewbox(region)
        if vb:
            hits = search({**base, "viewbox": vb, "bounded": 1})
            if hits:
                return {"bounded": True, "candidates": [_fmt(h) for h in hits]}
    hits = search(base)
    return {"bounded": False, "candidates": [_fmt(h) for h in hits]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", required=True)
    ap.add_argument("--region")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    print(json.dumps(geocode(args.query, args.region, args.limit),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_geocode.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skill/scripts/geocode.py tests/test_geocode.py
git -c commit.gpgsign=false commit -m "feat: Nominatim geocoding with region-bounded search and fallback

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Routing CLI (`route.py`)

**Files:**
- Create: `skill/scripts/route.py`
- Test: `tests/test_route.py`

**Interfaces:**
- Consumes: `common.USER_AGENT`
- Produces: `route.route(mode, coords) -> dict` where `mode ∈ {"foot","bike","car"}`, `coords` is `[(lat, lon), ...]` (start, vias…, end), returning `{geometry: str (polyline5), distance_m: int, duration_s: int}`; raises `RuntimeError` on OSRM errors. CLI `python3 skill/scripts/route.py --mode foot --coords "lat,lon;lat,lon[;...]"` printing that dict as JSON.

- [ ] **Step 1: Write the failing tests**

`tests/test_route.py`:
```python
import pytest

import route


class FakeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


OK_BODY = {
    "code": "Ok",
    "routes": [{"geometry": "abc123", "distance": 851.4, "duration": 639.6}],
}


def test_route_builds_fossgis_url_lon_lat_order(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)
        return FakeResp(OK_BODY)

    monkeypatch.setattr(route.requests, "get", fake_get)
    r = route.route("foot", [(41.8902, 12.4922), (41.8925, 12.4853)])
    assert r == {"geometry": "abc123", "distance_m": 851, "duration_s": 640}
    assert seen["url"].startswith(
        "https://routing.openstreetmap.de/routed-foot/route/v1/driving/"
    )
    # OSRM wants lon,lat
    assert "12.492200,41.890200;12.485300,41.892500" in seen["url"]
    assert seen["params"]["overview"] == "full"
    assert "wentro" in seen["headers"]["User-Agent"]


def test_route_includes_via_points(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        return FakeResp(OK_BODY)

    monkeypatch.setattr(route.requests, "get", fake_get)
    route.route("bike", [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])
    assert "routed-bike" in seen["url"]
    assert seen["url"].count(";") == 2


def test_route_error_raises(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResp({"code": "NoRoute", "message": "no route"})

    monkeypatch.setattr(route.requests, "get", fake_get)
    with pytest.raises(RuntimeError, match="NoRoute"):
        route.route("car", [(1.0, 2.0), (3.0, 4.0)])


def test_unknown_mode_rejected():
    with pytest.raises(KeyError):
        route.route("transit", [(1.0, 2.0), (3.0, 4.0)])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_route.py -v`
Expected: FAIL with "No module named 'route'"

- [ ] **Step 3: Implement `skill/scripts/route.py`**

```python
"""Routing via the public FOSSGIS OSRM instances (foot / bike / car).

The official OSRM demo server only serves the driving profile, so we use
routing.openstreetmap.de, which runs one instance per profile.
"""
import argparse
import json

import requests

from common import USER_AGENT

BASE = "https://routing.openstreetmap.de"
PROFILES = {"foot": "routed-foot", "bike": "routed-bike", "car": "routed-car"}


def route(mode, coords):
    """coords: [(lat, lon), ...] — start, via points..., end."""
    profile = PROFILES[mode]
    path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
    url = f"{BASE}/{profile}/route/v1/driving/{path}"
    r = requests.get(
        url,
        params={"overview": "full", "geometries": "polyline", "steps": "false"},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "Ok" or not body.get("routes"):
        raise RuntimeError(
            f"OSRM: {body.get('code')} {body.get('message', '')}".strip()
        )
    rt = body["routes"][0]
    return {
        "geometry": rt["geometry"],
        "distance_m": round(rt["distance"]),
        "duration_s": round(rt["duration"]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True, choices=sorted(PROFILES))
    ap.add_argument("--coords", required=True,
                    help='semicolon-separated "lat,lon" pairs: start;via...;end')
    args = ap.parse_args()
    coords = [tuple(map(float, pair.split(","))) for pair in args.coords.split(";")]
    print(json.dumps(route(args.mode, coords), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_route.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skill/scripts/route.py tests/test_route.py
git -c commit.gpgsign=false commit -m "feat: OSRM routing via FOSSGIS instances with via-point support

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Basemap tiles (`tiles.py`)

**Files:**
- Create: `skill/scripts/tiles.py`
- Test: `tests/test_tiles.py`

**Interfaces:**
- Consumes: `common.USER_AGENT`, `common.lonlat_to_global_px`
- Produces: `tiles.pad_bbox(minlon, minlat, maxlon, maxlat, frac=0.1) -> tuple4`; `tiles.choose_zoom(bbox, target_px=1280, max_tiles=80) -> int`; `tiles.build(bbox, out_path, target_px=1280, max_tiles=80) -> dict` meta `{zoom, origin_px_x, origin_px_y, width, height}` (origin = global px of image top-left; overlay projection is `global_px - origin`); `tiles.fetch_tile(z, x, y, session) -> PIL.Image` (network touchpoint — tests monkeypatch it). CLI `python3 skill/scripts/tiles.py --bbox "minlon,minlat,maxlon,maxlat" --out map.png [--meta-out meta.json]` writing the PNG and printing/writing meta JSON. On build failure, main retries once with `target_px` halved (lower zoom).

- [ ] **Step 1: Write the failing tests**

`tests/test_tiles.py`:
```python
import json

from PIL import Image

import tiles
from common import lonlat_to_global_px

ROME_BBOX = (12.4731, 41.8902, 12.4922, 41.9009)


def test_pad_bbox_expands_and_enforces_min_span():
    b = tiles.pad_bbox(12.48, 41.89, 12.48, 41.89)  # degenerate point
    assert b[2] - b[0] >= 0.002
    assert b[3] - b[1] >= 0.002
    b2 = tiles.pad_bbox(*ROME_BBOX)
    assert b2[0] < ROME_BBOX[0] and b2[2] > ROME_BBOX[2]


def test_choose_zoom_respects_constraints():
    bbox = tiles.pad_bbox(*ROME_BBOX)
    z = tiles.choose_zoom(bbox, target_px=1280, max_tiles=80)
    assert 1 <= z <= 19
    x0, y0 = lonlat_to_global_px(bbox[0], bbox[3], z)
    x1, y1 = lonlat_to_global_px(bbox[2], bbox[1], z)
    assert max(x1 - x0, y1 - y0) <= 1280
    ntiles = (int(x1 // 256) - int(x0 // 256) + 1) * (int(y1 // 256) - int(y0 // 256) + 1)
    assert ntiles <= 80


def test_choose_zoom_smaller_bbox_gets_deeper_zoom():
    small = tiles.pad_bbox(12.4731, 41.8902, 12.4922, 41.9009)
    big = tiles.pad_bbox(12.0, 41.5, 13.0, 42.3)
    assert tiles.choose_zoom(small) > tiles.choose_zoom(big)


def test_build_stitches_and_reports_meta(tmp_path, monkeypatch):
    fetched = []

    def fake_fetch(z, x, y, session):
        fetched.append((z, x, y))
        return Image.new("RGB", (256, 256), (200, 210, 220))

    monkeypatch.setattr(tiles, "fetch_tile", fake_fetch)
    monkeypatch.setattr(tiles.time, "sleep", lambda s: None)
    out = tmp_path / "map.png"
    meta = tiles.build(ROME_BBOX, out)
    img = Image.open(out)
    assert (img.width, img.height) == (meta["width"], meta["height"])
    assert meta["zoom"] == tiles.choose_zoom(tiles.pad_bbox(*ROME_BBOX))
    assert len(fetched) <= 80
    # origin must be the global pixel of the image's top-left corner
    b = tiles.pad_bbox(*ROME_BBOX)
    x0, y0 = lonlat_to_global_px(b[0], b[3], meta["zoom"])
    assert abs(meta["origin_px_x"] - x0) < 1
    assert abs(meta["origin_px_y"] - y0) < 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tiles.py -v`
Expected: FAIL with "No module named 'tiles'"

- [ ] **Step 3: Implement `skill/scripts/tiles.py`**

```python
"""Download and stitch OSM tiles for a bounding box.

Writes a cropped PNG basemap and returns georeference metadata:
origin_px_* is the Web-Mercator global pixel of the image's top-left
corner at the chosen zoom, so overlays project with global_px - origin.
"""
import argparse
import io
import json
import time

import requests
from PIL import Image

from common import USER_AGENT, lonlat_to_global_px

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE = 256


def pad_bbox(minlon, minlat, maxlon, maxlat, frac=0.1):
    """Pad by frac per side around the center; enforce a minimum span."""
    cx, cy = (minlon + maxlon) / 2, (minlat + maxlat) / 2
    half_w = max(maxlon - minlon, 0.002) * (1 + 2 * frac) / 2
    half_h = max(maxlat - minlat, 0.002) * (1 + 2 * frac) / 2
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def choose_zoom(bbox, target_px=1280, max_tiles=80):
    """Deepest zoom whose padded bbox fits target_px and the tile budget."""
    minlon, minlat, maxlon, maxlat = bbox
    for z in range(19, 0, -1):
        x0, y0 = lonlat_to_global_px(minlon, maxlat, z)
        x1, y1 = lonlat_to_global_px(maxlon, minlat, z)
        ntiles = (int(x1 // TILE) - int(x0 // TILE) + 1) * (
            int(y1 // TILE) - int(y0 // TILE) + 1
        )
        if max(x1 - x0, y1 - y0) <= target_px and ntiles <= max_tiles:
            return z
    return 1


def fetch_tile(z, x, y, session):
    """Fetch one tile, retrying once. The only network touchpoint here."""
    for attempt in (1, 2):
        try:
            r = session.get(
                TILE_URL.format(z=z, x=x, y=y),
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1)


def build(bbox, out_path, target_px=1280, max_tiles=80):
    bbox = pad_bbox(*bbox)
    z = choose_zoom(bbox, target_px, max_tiles)
    minlon, minlat, maxlon, maxlat = bbox
    x0, y0 = lonlat_to_global_px(minlon, maxlat, z)
    x1, y1 = lonlat_to_global_px(maxlon, minlat, z)
    tx0, ty0 = int(x0 // TILE), int(y0 // TILE)
    tx1, ty1 = int(x1 // TILE), int(y1 // TILE)
    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE))
    with requests.Session() as session:
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                tile = fetch_tile(z, tx, ty, session)
                canvas.paste(tile, ((tx - tx0) * TILE, (ty - ty0) * TILE))
                time.sleep(0.15)  # sequential + pause: polite to tile.osm.org
    left, top = x0 - tx0 * TILE, y0 - ty0 * TILE
    img = canvas.crop(
        (round(left), round(top), round(x1 - tx0 * TILE), round(y1 - ty0 * TILE))
    )
    img.save(out_path)
    return {
        "zoom": z,
        "origin_px_x": x0,
        "origin_px_y": y0,
        "width": img.width,
        "height": img.height,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", required=True, help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta-out")
    ap.add_argument("--target-px", type=int, default=1280)
    ap.add_argument("--max-tiles", type=int, default=80)
    args = ap.parse_args()
    bbox = tuple(map(float, args.bbox.split(",")))
    try:
        meta = build(bbox, args.out, args.target_px, args.max_tiles)
    except requests.RequestException:
        # Fallback: drop a zoom level by halving the pixel target.
        meta = build(bbox, args.out, args.target_px // 2, args.max_tiles)
    out = json.dumps(meta, indent=2)
    if args.meta_out:
        with open(args.meta_out, "w", encoding="utf-8") as f:
            f.write(out)
    print(out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tiles.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skill/scripts/tiles.py tests/test_tiles.py
git -c commit.gpgsign=false commit -m "feat: OSM tile fetch, zoom selection, stitch and crop with georef meta

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Renderer (`render.py` + `templates/map.html`)

**Files:**
- Create: `skill/scripts/render.py`, `templates/map.html`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `common.load_itinerary`, `common.decode_polyline`, `common.lonlat_to_global_px`; tiles meta dict from Task 6.
- Produces: `render.build_payload(data, meta, basemap_path) -> dict` (`title, region, image (data URI), width, height, points[{n,name,resolved,x,y}], legs[{mode,color,dashed,path,note,distance_m,duration_s}], totals{distance_m,duration_s}`); `render.render_html(payload, template_path, out_path)`; `render.render_png(payload, basemap_path, out_path, long_side=2000)`; `render.MODE_COLORS: dict`. CLI `python3 skill/scripts/render.py --itinerary I.json --basemap map.png --meta meta.json --template templates/map.html --out-html page.html --out-png share.png`.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:
```python
import json

from PIL import Image

import render
from common import lonlat_to_global_px


def fixture(tmp_path):
    data = {
        "title": "Mini Walk",
        "region": "Rome, Italy",
        "points": [
            {"id": "p1", "name": "斗兽场", "resolved": "Colosseo", "lat": 41.8902, "lon": 12.4922},
            {"id": "p2", "name": "Foro Romano", "resolved": "Foro Romano", "lat": 41.8925, "lon": 12.4853},
        ],
        "legs": [
            {"from": "p1", "to": "p2", "mode": "foot", "via": [],
             "geometry": None, "distance_m": 850, "duration_s": 640},
        ],
    }
    zoom = 16
    x0, y0 = lonlat_to_global_px(12.4820, 41.8950, zoom)  # NW of both points
    meta = {"zoom": zoom, "origin_px_x": x0, "origin_px_y": y0,
            "width": 800, "height": 600}
    basemap = tmp_path / "base.png"
    Image.new("RGB", (800, 600), (230, 228, 224)).save(basemap)
    return data, meta, basemap


def test_build_payload_projects_points(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    p = render.build_payload(data, meta, basemap)
    assert p["title"] == "Mini Walk"
    assert p["image"].startswith("data:image/png;base64,")
    assert len(p["points"]) == 2
    assert p["points"][0]["n"] == 1
    x, y = p["points"][0]["x"], p["points"][0]["y"]
    ex, ey = lonlat_to_global_px(12.4922, 41.8902, meta["zoom"])
    assert abs(x - (ex - meta["origin_px_x"])) < 0.5
    assert abs(y - (ey - meta["origin_px_y"])) < 0.5


def test_missing_geometry_renders_dashed_straight_line(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    p = render.build_payload(data, meta, basemap)
    leg = p["legs"][0]
    assert leg["dashed"] is True  # no geometry -> approximate
    assert len(leg["path"]) == 2


def test_totals_sum(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    p = render.build_payload(data, meta, basemap)
    assert p["totals"] == {"distance_m": 850, "duration_s": 640}


def test_render_html_injects_payload(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    p = render.build_payload(data, meta, basemap)
    out = tmp_path / "page.html"
    render.render_html(p, "templates/map.html", out)
    html = out.read_text()
    assert "/*__WENTRO_DATA__*/null" not in html
    assert "__WENTRO_TITLE__" not in html
    assert "Mini Walk" in html
    assert "OpenStreetMap" in html  # attribution present


def test_render_png_upscales_to_long_side(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    p = render.build_payload(data, meta, basemap)
    out = tmp_path / "share.png"
    render.render_png(p, basemap, out, long_side=1600)
    img = Image.open(out)
    assert max(img.size) == 1600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL with "No module named 'render'"

- [ ] **Step 3: Write `templates/map.html`**

No doctype/html/head/body tags — the artifact wrapper supplies them. Content:

```html
<title>__WENTRO_TITLE__</title>
<style>
  :root {
    --bg: #f6f4f1; --panel: #ffffff; --text: #22303c; --muted: #6b7280;
    --line: #e5e7eb; --chip: #f1f3f5;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14181d; --panel: #1c2229; --text: #e6e9ed; --muted: #98a2ae;
      --line: #2c333b; --chip: #262d35;
    }
  }
  :root[data-theme="dark"] {
    --bg: #14181d; --panel: #1c2229; --text: #e6e9ed; --muted: #98a2ae;
    --line: #2c333b; --chip: #262d35;
  }
  body { background: var(--bg); color: var(--text);
         font: 15px/1.5 -apple-system, "Segoe UI", "PingFang SC", sans-serif; margin: 0; }
  #app { display: flex; height: 100vh; }
  #panel { width: 300px; flex: none; background: var(--panel); overflow-y: auto;
           border-right: 1px solid var(--line); padding: 16px; box-sizing: border-box; }
  #panel h1 { font-size: 18px; margin: 0 0 2px; }
  #panel .region { color: var(--muted); font-size: 13px; margin-bottom: 12px; }
  .pt { display: flex; align-items: baseline; gap: 8px; padding: 6px 8px;
        border-radius: 8px; cursor: pointer; }
  .pt:hover, .pt.active { background: var(--chip); }
  .pt .num { flex: none; width: 22px; height: 22px; border-radius: 50%;
             background: #364fc7; color: #fff; font-size: 12px; font-weight: 700;
             display: flex; align-items: center; justify-content: center;
             align-self: center; }
  .pt .res { color: var(--muted); font-size: 12px; display: block; }
  .leg { color: var(--muted); font-size: 13px; padding: 2px 8px 2px 38px; }
  #totals { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line);
            font-size: 13px; color: var(--muted); }
  #mapwrap { flex: 1; position: relative; overflow: hidden; background: #dfe8ef; }
  #viewport { position: absolute; transform-origin: 0 0; }
  #viewport img { display: block; user-select: none; -webkit-user-drag: none; }
  #viewport svg { position: absolute; left: 0; top: 0; }
  #attr { position: absolute; right: 4px; bottom: 4px; background: rgba(255,255,255,.85);
          color: #333; font-size: 11px; padding: 1px 6px; border-radius: 4px; }
  #zoomctl { position: absolute; left: 10px; top: 10px; display: flex;
             flex-direction: column; gap: 6px; }
  #zoomctl button { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--line);
                    background: var(--panel); color: var(--text); font-size: 18px; cursor: pointer; }
  @media (max-width: 700px) {
    #app { flex-direction: column; }
    #panel { width: auto; max-height: 40vh; border-right: 0; border-bottom: 1px solid var(--line); }
  }
</style>
<div id="app">
  <aside id="panel">
    <h1 id="t"></h1>
    <div class="region" id="r"></div>
    <div id="list"></div>
    <div id="totals"></div>
  </aside>
  <main id="mapwrap">
    <div id="viewport"><img id="basemap" alt=""><svg id="overlay" xmlns="http://www.w3.org/2000/svg"></svg></div>
    <div id="zoomctl"><button id="zin">+</button><button id="zout">−</button></div>
    <div id="attr">© OpenStreetMap contributors</div>
  </main>
</div>
<script>
const DATA = /*__WENTRO_DATA__*/null;
const NS = "http://www.w3.org/2000/svg";
const fmtKm = m => m == null ? "" : (m / 1000).toFixed(m < 950 ? 2 : 1) + " km";
const fmtMin = s => s == null ? "" : "~" + Math.max(1, Math.round(s / 60)) + " min";
const MODE_ICON = { foot: "🚶", bike: "🚲", car: "🚗", transit: "🚇" };

document.getElementById("t").textContent = DATA.title;
document.getElementById("r").textContent = DATA.region;
document.title = DATA.title;

const img = document.getElementById("basemap");
img.src = DATA.image; img.width = DATA.width; img.height = DATA.height;
const svg = document.getElementById("overlay");
svg.setAttribute("width", DATA.width); svg.setAttribute("height", DATA.height);
svg.setAttribute("viewBox", `0 0 ${DATA.width} ${DATA.height}`);

for (const leg of DATA.legs) {
  const pl = document.createElementNS(NS, "polyline");
  pl.setAttribute("points", leg.path.map(p => p.join(",")).join(" "));
  pl.setAttribute("fill", "none");
  pl.setAttribute("stroke", leg.color);
  pl.setAttribute("stroke-width", "5");
  pl.setAttribute("stroke-linecap", "round");
  pl.setAttribute("stroke-linejoin", "round");
  pl.setAttribute("opacity", "0.85");
  if (leg.dashed) pl.setAttribute("stroke-dasharray", "10 8");
  svg.appendChild(pl);
}
for (const p of DATA.points) {
  const g = document.createElementNS(NS, "g");
  g.setAttribute("id", "mk-" + p.n);
  const c = document.createElementNS(NS, "circle");
  c.setAttribute("cx", p.x); c.setAttribute("cy", p.y); c.setAttribute("r", "11");
  c.setAttribute("fill", "#364fc7"); c.setAttribute("stroke", "#fff");
  c.setAttribute("stroke-width", "2.5");
  const t = document.createElementNS(NS, "text");
  t.setAttribute("x", p.x); t.setAttribute("y", p.y);
  t.setAttribute("fill", "#fff"); t.setAttribute("font-size", "11");
  t.setAttribute("font-weight", "700"); t.setAttribute("text-anchor", "middle");
  t.setAttribute("dominant-baseline", "central");
  t.textContent = p.n;
  g.appendChild(c); g.appendChild(t); svg.appendChild(g);
}

// Side panel: point rows interleaved with leg rows.
const list = document.getElementById("list");
DATA.points.forEach((p, i) => {
  const row = document.createElement("div");
  row.className = "pt"; row.id = "row-" + p.n;
  row.innerHTML = `<span class="num">${p.n}</span><span><span class="nm"></span>` +
                  `<span class="res"></span></span>`;
  row.querySelector(".nm").textContent = p.name;
  row.querySelector(".res").textContent = p.resolved || "";
  row.addEventListener("click", () => highlight(p));
  list.appendChild(row);
  const leg = DATA.legs[i];
  if (leg) {
    const lr = document.createElement("div");
    lr.className = "leg";
    const bits = [MODE_ICON[leg.mode] || "", fmtKm(leg.distance_m),
                  fmtMin(leg.duration_s), leg.note || ""].filter(Boolean);
    lr.textContent = "↓ " + bits.join(" · ");
    list.appendChild(lr);
  }
});
const tot = DATA.totals;
document.getElementById("totals").textContent =
  `Total: ${fmtKm(tot.distance_m)} · ${fmtMin(tot.duration_s)}`;

// Pan & zoom.
const wrap = document.getElementById("mapwrap");
const vp = document.getElementById("viewport");
let k = 1, minK = 1, tx = 0, ty = 0;
function apply() { vp.style.transform = `translate(${tx}px,${ty}px) scale(${k})`; }
function fit() {
  minK = Math.min(wrap.clientWidth / DATA.width, wrap.clientHeight / DATA.height);
  k = minK;
  tx = (wrap.clientWidth - DATA.width * k) / 2;
  ty = (wrap.clientHeight - DATA.height * k) / 2;
  apply();
}
function zoomAt(f, cx, cy) {
  const nk = Math.min(2.5, Math.max(minK, k * f));
  tx = cx - (cx - tx) * (nk / k); ty = cy - (cy - ty) * (nk / k);
  k = nk; apply();
}
let drag = null;
wrap.addEventListener("pointerdown", e => {
  drag = { x: e.clientX - tx, y: e.clientY - ty }; wrap.setPointerCapture(e.pointerId);
});
wrap.addEventListener("pointermove", e => {
  if (drag) { tx = e.clientX - drag.x; ty = e.clientY - drag.y; apply(); }
});
wrap.addEventListener("pointerup", () => { drag = null; });
wrap.addEventListener("wheel", e => {
  e.preventDefault();
  const r = wrap.getBoundingClientRect();
  zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
}, { passive: false });
document.getElementById("zin").addEventListener("click",
  () => zoomAt(1.3, wrap.clientWidth / 2, wrap.clientHeight / 2));
document.getElementById("zout").addEventListener("click",
  () => zoomAt(1 / 1.3, wrap.clientWidth / 2, wrap.clientHeight / 2));
window.addEventListener("resize", fit);
fit();

function highlight(p) {
  document.querySelectorAll(".pt.active").forEach(el => el.classList.remove("active"));
  document.getElementById("row-" + p.n).classList.add("active");
  document.querySelectorAll("#overlay circle").forEach(c => c.setAttribute("r", "11"));
  const mk = document.querySelector("#mk-" + CSS.escape(String(p.n)) + " circle");
  mk.setAttribute("r", "15");
  // Center the marker in the viewport at current zoom.
  tx = wrap.clientWidth / 2 - p.x * k; ty = wrap.clientHeight / 2 - p.y * k; apply();
}
</script>
```

- [ ] **Step 4: Implement `skill/scripts/render.py`**

```python
"""Render an itinerary to interactive HTML and a static PNG share image."""
import argparse
import base64
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import decode_polyline, load_itinerary, lonlat_to_global_px

MODE_COLORS = {"foot": "#e8590c", "bike": "#2f9e44", "car": "#1971c2",
               "transit": "#9c36b5"}
MARKER = "#364fc7"


def _project(lon, lat, meta):
    x, y = lonlat_to_global_px(lon, lat, meta["zoom"])
    return x - meta["origin_px_x"], y - meta["origin_px_y"]


def _leg_coords(leg, pts):
    if leg.get("geometry"):
        return decode_polyline(leg["geometry"])
    a, b = pts[leg["from"]], pts[leg["to"]]
    return [(a["lat"], a["lon"]), (b["lat"], b["lon"])]


def build_payload(data, meta, basemap_path):
    pts = {p["id"]: p for p in data["points"]}
    img_b64 = base64.b64encode(Path(basemap_path).read_bytes()).decode()
    payload = {
        "title": data["title"],
        "region": data["region"],
        "image": "data:image/png;base64," + img_b64,
        "width": meta["width"],
        "height": meta["height"],
        "points": [],
        "legs": [],
        "totals": {"distance_m": 0, "duration_s": 0},
    }
    for i, p in enumerate(data["points"], 1):
        x, y = _project(p["lon"], p["lat"], meta)
        payload["points"].append({
            "n": i, "name": p["name"], "resolved": p.get("resolved"),
            "x": round(x, 1), "y": round(y, 1),
        })
    for leg in data["legs"]:
        path = [_project(lon, lat, meta) for lat, lon in _leg_coords(leg, pts)]
        payload["legs"].append({
            "mode": leg["mode"],
            "color": MODE_COLORS[leg["mode"]],
            "dashed": (leg["mode"] == "transit" or leg.get("approximate", False)
                       or not leg.get("geometry")),
            "path": [[round(x, 1), round(y, 1)] for x, y in path],
            "note": leg.get("note"),
            "distance_m": leg.get("distance_m"),
            "duration_s": leg.get("duration_s"),
        })
        payload["totals"]["distance_m"] += leg.get("distance_m") or 0
        payload["totals"]["duration_s"] += leg.get("duration_s") or 0
    return payload


def render_html(payload, template_path, out_path):
    html = Path(template_path).read_text(encoding="utf-8")
    html = html.replace("__WENTRO_TITLE__", payload["title"])
    html = html.replace("/*__WENTRO_DATA__*/null",
                        json.dumps(payload, ensure_ascii=False))
    Path(out_path).write_text(html, encoding="utf-8")


def _dashed_line(draw, pts, color, width, dash=16, gap=10):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg == 0:
            continue
        ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
        t = 0.0
        while t < seg:
            e = min(t + dash, seg)
            draw.line([(x1 + ux * t, y1 + uy * t), (x1 + ux * e, y1 + uy * e)],
                      fill=color, width=width)
            t = e + gap


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow fallback
        return ImageFont.load_default()


def render_png(payload, basemap_path, out_path, long_side=2000):
    img = Image.open(basemap_path).convert("RGB")
    s = long_side / max(img.size)
    s = min(2.0, s) if s > 1 else 1.0
    if s != 1.0:
        img = img.resize((round(img.width * s), round(img.height * s)),
                         Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    lw = max(4, round(img.width / 280))
    for leg in payload["legs"]:
        path = [(x * s, y * s) for x, y in leg["path"]]
        if len(path) < 2:
            continue
        if leg["dashed"]:
            _dashed_line(draw, path, leg["color"], lw)
        else:
            draw.line(path, fill=leg["color"], width=lw, joint="curve")
    r = max(11, round(img.width / 110))
    num_font = _font(round(r * 1.1))
    for p in payload["points"]:
        x, y = p["x"] * s, p["y"] * s
        draw.ellipse([x - r, y - r, x + r, y + r], fill=MARKER,
                     outline="white", width=max(2, r // 5))
        draw.text((x, y), str(p["n"]), font=num_font, fill="white", anchor="mm")
    title_font = _font(max(18, img.width // 55))
    small_font = _font(max(11, img.width // 120))
    pad = img.width // 90
    tb = draw.textbbox((0, 0), payload["title"], font=title_font)
    draw.rounded_rectangle(
        [pad, pad, pad * 3 + (tb[2] - tb[0]), pad * 2 + (tb[3] - tb[1]) + pad // 2],
        radius=pad // 2, fill="white", outline="#d2d2d2")
    draw.text((pad * 2, pad + pad // 2), payload["title"], font=title_font,
              fill="#22303c")
    attr = "© OpenStreetMap contributors"
    ab = draw.textbbox((0, 0), attr, font=small_font)
    aw, ah = ab[2] - ab[0], ab[3] - ab[1]
    draw.rectangle([img.width - aw - 12, img.height - ah - 10,
                    img.width, img.height], fill=(255, 255, 255))
    draw.text((img.width - aw - 6, img.height - ah - 6), attr,
              font=small_font, fill="#333333")
    img.save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--itinerary", required=True)
    ap.add_argument("--basemap", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out-html", required=True)
    ap.add_argument("--out-png")
    args = ap.parse_args()
    data = load_itinerary(args.itinerary)
    meta = json.loads(Path(args.meta).read_text())
    payload = build_payload(data, meta, args.basemap)
    render_html(payload, args.template, args.out_html)
    if args.out_png:
        render_png(payload, args.basemap, args.out_png)
    print(json.dumps({"html": args.out_html, "png": args.out_png,
                      "points": len(payload["points"])}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render.py -v` (run from repo root so `templates/map.html` resolves)
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add skill/scripts/render.py templates/map.html tests/test_render.py
git -c commit.gpgsign=false commit -m "feat: HTML + PNG renderer with pan/zoom template and OSM attribution

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Example itinerary + offline pipeline test

**Files:**
- Create: `examples/rome-walk.json`
- Test: `tests/test_pipeline_offline.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7. No new interfaces.

- [ ] **Step 1: Write `examples/rome-walk.json`**

Input-state example (geometry/metrics null — a real build fills them):
```json
{
  "title": "Classic Rome Walk",
  "region": "Rome, Italy",
  "points": [
    {"id": "p1", "name": "斗兽场", "query": "Colosseum, Rome", "resolved": "Colosseo, Roma", "lat": 41.8902, "lon": 12.4922, "photos": []},
    {"id": "p2", "name": "古罗马广场", "query": "Roman Forum, Rome", "resolved": "Foro Romano, Roma", "lat": 41.8925, "lon": 12.4853, "photos": []},
    {"id": "p3", "name": "特雷维喷泉", "query": "Trevi Fountain, Rome", "resolved": "Fontana di Trevi, Roma", "lat": 41.9009, "lon": 12.4833, "photos": []},
    {"id": "p4", "name": "万神殿", "query": "Pantheon, Rome", "resolved": "Pantheon, Roma", "lat": 41.8986, "lon": 12.4769, "photos": []},
    {"id": "p5", "name": "纳沃纳广场", "query": "Piazza Navona, Rome", "resolved": "Piazza Navona, Roma", "lat": 41.8992, "lon": 12.4731, "photos": []}
  ],
  "legs": [
    {"from": "p1", "to": "p2", "mode": "foot", "via": [], "geometry": null, "distance_m": null, "duration_s": null},
    {"from": "p2", "to": "p3", "mode": "foot", "via": [], "geometry": null, "distance_m": null, "duration_s": null},
    {"from": "p3", "to": "p4", "mode": "foot", "via": [], "geometry": null, "distance_m": null, "duration_s": null},
    {"from": "p4", "to": "p5", "mode": "foot", "via": [], "geometry": null, "distance_m": null, "duration_s": null}
  ],
  "artifact_url": null,
  "updated": "2026-08-22"
}
```

- [ ] **Step 2: Write the offline end-to-end test**

`tests/test_pipeline_offline.py`:
```python
"""Full pipeline against the committed example, all network mocked."""
import json

from PIL import Image

import render
import tiles
import validate
from common import load_itinerary


def test_example_validates_and_renders(tmp_path, monkeypatch):
    data = load_itinerary("examples/rome-walk.json")  # chain invariant holds
    assert validate.check(data)["ok"]

    monkeypatch.setattr(
        tiles, "fetch_tile",
        lambda z, x, y, s: Image.new("RGB", (256, 256), (220, 224, 228)))
    monkeypatch.setattr(tiles.time, "sleep", lambda s: None)

    lats = [p["lat"] for p in data["points"]]
    lons = [p["lon"] for p in data["points"]]
    basemap = tmp_path / "map.png"
    meta = tiles.build((min(lons), min(lats), max(lons), max(lats)), basemap)

    payload = render.build_payload(data, meta, basemap)
    # Every projected point must land inside the image.
    for p in payload["points"]:
        assert 0 <= p["x"] <= meta["width"]
        assert 0 <= p["y"] <= meta["height"]

    out_html = tmp_path / "page.html"
    out_png = tmp_path / "share.png"
    render.render_html(payload, "templates/map.html", out_html)
    render.render_png(payload, basemap, out_png)
    assert "Classic Rome Walk" in out_html.read_text()
    assert Image.open(out_png).width > 0
```

- [ ] **Step 3: Run the test**

Run: `python3 -m pytest tests/test_pipeline_offline.py -v`
Expected: PASS (points land inside the image because tiles.build pads the bbox)

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add examples/rome-walk.json tests/test_pipeline_offline.py
git -c commit.gpgsign=false commit -m "feat: example itinerary and offline end-to-end pipeline test

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: SKILL.md — the workflow

**Files:**
- Create: `skill/SKILL.md`

**Interfaces:**
- Consumes: all CLI contracts from Tasks 3–7 (exact commands below).

- [ ] **Step 1: Write `skill/SKILL.md`**

````markdown
---
name: wentro
description: Turn a finished trip into a shareable itinerary map (post-trip recap, not planning). Use when the user wants to create, update, or share a route map of places they visited — start, waypoints, destination, transport modes. Triggers on "行程图", "旅行路线图", "itinerary map", "trip map", "travel recap", "wentro".
---

# Wentro — post-trip itinerary maps

Turn a finished trip into (1) an interactive map artifact and (2) a static
PNG share image. All network work happens conversation-side via the scripts
in `scripts/` — the published artifact makes no external requests.

**Source of truth:** one JSON file per itinerary. Data directory:
`./itineraries/` if it exists in the working directory, else
`~/.wentro/itineraries/`. Never regenerate from chat memory when the file
exists — load it.

## Input contract

Minimum viable input: a region plus two or more places, in any language.
If input is incomplete, do NOT guess — show this template:

> - Region (city or country): …
> - Places in visit order: …
> - How you moved between them (walking by default): …

## Parse & normalize (your job, not the scripts')

1. Validate: region present; ≥2 points; modes within foot/bike/car/transit.
2. Per place, build a geocoding `query`: fix typos, translate to the local
   language or English, append city context. Keep the user's wording as `name`.
3. Mode parsing — recognize three scopes with precedence
   per-leg > exception ("taxi to the airport, rest walking") > trip default
   ("all on foot"). Write the resolved mode on EVERY leg. If no mode was
   stated at any scope, use `foot` and flag the assumption in your reply.

## Pipeline (run from the repo root, or substitute the skill directory)

1. Geocode each point (~1 s per call — Nominatim rate limit):
   `python3 skill/scripts/geocode.py --query "Colosseum, Rome" --region "Rome, Italy"`
   → `{bounded, candidates:[{display_name, lat, lon, ...}]}`.
   Pick the best candidate; if ambiguous or `bounded: false`, show the top
   candidates and ask. Store lat/lon/resolved on the point.
2. Write the JSON; `common.save_itinerary` validates the chain invariant.
3. Coherence gate:
   `python3 skill/scripts/validate.py --itinerary itineraries/<slug>.json`
   Exit 1 = outlier hard error → re-geocode the flagged point; if it still
   fails, STOP and ask the user. Warnings → confirm with the user before
   proceeding. Never render a map with a known-suspect point.
4. Route each non-transit leg (lat,lon order; vias between endpoints):
   `python3 skill/scripts/route.py --mode foot --coords "41.8902,12.4922;41.8925,12.4853"`
   → store geometry/distance_m/duration_s on the leg. On RuntimeError:
   keep geometry null (renders as dashed approximate) and tell the user.
   Transit legs: no routing; write a human `note` ("Metro line B, ~8 min").
5. Basemap (bbox = min/max of all point coords; script pads it):
   `python3 skill/scripts/tiles.py --bbox "12.4731,41.8902,12.4922,41.9009" --out /tmp/wentro-map.png --meta-out /tmp/wentro-meta.json`
6. Render:
   `python3 skill/scripts/render.py --itinerary itineraries/<slug>.json --basemap /tmp/wentro-map.png --meta /tmp/wentro-meta.json --template templates/map.html --out-html /tmp/wentro-page.html --out-png itineraries/<slug>.png`
7. Publish `/tmp/wentro-page.html` as an artifact. If the itinerary has an
   `artifact_url`, pass it as `url` so the SAME link updates. Store the
   returned URL in the JSON. Send the PNG to the user as a file.
8. Reply with: artifact link, the resolved-name list for eyeballing, and
   any assumptions or warnings.

## Update / delete

- Load the JSON (never rebuild from memory). Apply the edit:
  - add point → insert into `points`, split the leg, re-route both halves;
  - wrong route → derive `via` coordinate(s) from the user's description,
    add to that leg's `via`, re-route that leg only;
  - wrong point → replace/remove; merge adjacent legs on removal, re-route.
- Re-run steps 3–8. Tiles can be reused when the bbox is unchanged.
- The chain invariant is enforced on every save — if it trips, fix the
  legs list, don't bypass validation.

## Etiquette

Nominatim ≤1 req/s (built into geocode.py). Tiles ≤80/build, sequential
(built into tiles.py). Don't loop these scripts aggressively.
````

- [ ] **Step 2: Verify the CLI commands in SKILL.md against the implemented scripts**

Run each of these and confirm the flag names match (`--help`):
```bash
python3 skill/scripts/geocode.py --help
python3 skill/scripts/route.py --help
python3 skill/scripts/tiles.py --help
python3 skill/scripts/render.py --help
python3 skill/scripts/validate.py --help
```
Expected: every flag used in SKILL.md appears in the help output.

- [ ] **Step 3: Commit**

```bash
git add skill/SKILL.md
git -c commit.gpgsign=false commit -m "feat: SKILL.md workflow — input contract, pipeline, CRUD, etiquette

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: README, LICENSE, docs

**Files:**
- Create: `README.md`, `README.zh-CN.md`, `LICENSE`, `docs/data-format.md`, `docs/data-format.zh-CN.md`

- [ ] **Step 1: Write `LICENSE`**

MIT License, copyright line: `Copyright (c) 2026 ShawNova`. Standard MIT text (from https://opensource.org/license/mit, verbatim).

- [ ] **Step 2: Write `README.md`**

Sections (write full prose, English):
- Title: `# Wentro (温途)` + one-liner: *Retrace the journey you went. Turn a finished trip into a shareable itinerary map.*
- **What it is**: a Claude Code skill for post-trip recaps — NOT a trip planner. You tell Claude where you went (any language); it geocodes real places (Nominatim), fetches real routes (FOSSGIS OSRM: walking/cycling/driving; transit legs rendered schematically), stitches an OpenStreetMap basemap, and produces an interactive map artifact plus a static PNG share image.
- **Why conversation-side**: artifacts run under a strict CSP with no network access, so Claude does the data work and bakes everything into a self-contained page.
- **Install**:
  ```bash
  git clone https://github.com/ShawNova/wentro.git
  cd wentro && pip install -r requirements.txt
  ln -s "$(pwd)/skill" ~/.claude/skills/wentro
  ```
- **Usage**: example conversation (create with mixed modes, add a point, fix a route with a via, delete a point). Input template quoted from SKILL.md.
- **Data**: link to docs/data-format.md; note `./itineraries/` vs `~/.wentro/itineraries/` resolution; itinerary JSON is the source of truth and survives across sessions.
- **Etiquette & attribution**: OSM/Nominatim/FOSSGIS usage policies respected (UA, rate limits, ≤80 tiles); maps © OpenStreetMap contributors.
- **Roadmap**: photo insertion per point (field reserved).
- **License**: MIT. Language note: `[中文说明](README.zh-CN.md)` link under the title.

- [ ] **Step 3: Write `README.zh-CN.md`**

Faithful Chinese mirror of README.md (not word-for-word; same sections, same commands, `[English](README.md)` link at top).

- [ ] **Step 4: Write `docs/data-format.md` and `docs/data-format.zh-CN.md`**

Document every field of the itinerary JSON (copy the annotated example from the design doc `docs/specs/2026-08-22-wentro-design.md` §Data model), the chain invariant, mode values, `via` semantics, `photos` reserved field, and the data-directory resolution rule. Chinese mirror.

- [ ] **Step 5: Commit**

```bash
git add README.md README.zh-CN.md LICENSE docs/data-format.md docs/data-format.zh-CN.md
git -c commit.gpgsign=false commit -m "docs: README (EN/zh-CN), MIT license, data format reference

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Live verification + install + push

This task uses real network services (politely: 1 region + 5 place geocodes, 4 OSRM calls, ≤80 tiles) and publishes a real artifact.

- [ ] **Step 1: Run the real pipeline on the Rome example**

```bash
cp examples/rome-walk.json itineraries/rome-walk.json
python3 skill/scripts/validate.py --itinerary itineraries/rome-walk.json
for pair in "41.8902,12.4922;41.8925,12.4853" "41.8925,12.4853;41.9009,12.4833" "41.9009,12.4833;41.8986,12.4769" "41.8986,12.4769;41.8992,12.4731"; do
  python3 skill/scripts/route.py --mode foot --coords "$pair"
done
```
Write each route result (geometry, distance_m, duration_s) into the corresponding leg of `itineraries/rome-walk.json`, then:
```bash
python3 skill/scripts/tiles.py --bbox "12.4731,41.8902,12.4922,41.9009" --out /tmp/wentro-map.png --meta-out /tmp/wentro-meta.json
python3 skill/scripts/render.py --itinerary itineraries/rome-walk.json --basemap /tmp/wentro-map.png --meta /tmp/wentro-meta.json --template templates/map.html --out-html /tmp/wentro-page.html --out-png /tmp/wentro-share.png
```
Expected: real walking distances 500–1500 m per leg; PNG shows routes following streets, not straight lines.

- [ ] **Step 2: Publish and inspect**

Publish `/tmp/wentro-page.html` with the Artifact tool (load the artifact-design skill first, favicon 🗺️); send `/tmp/wentro-share.png` to the user with SendUserFile. Open the artifact in the browser pane and verify: basemap visible, 5 numbered markers, orange route lines on streets, side panel totals, pan and zoom work.

- [ ] **Step 3: Install the skill and push**

```bash
ln -sfn "$(pwd)/skill" ~/.claude/skills/wentro
python3 -m pytest tests/ -q
git push
```
Expected: all tests pass; branch pushed to github.com/ShawNova/wentro.

- [ ] **Step 4: Report**

Tell the user: artifact URL, PNG location, skill installed, repo pushed. Note that the demo itinerary JSON stays local (itineraries/ is gitignored).

