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
