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
