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
