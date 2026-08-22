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
