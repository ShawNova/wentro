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
