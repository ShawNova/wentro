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


def test_render_png_downscales_oversized_basemap(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    # Create a 3000×2000 basemap (oversized)
    oversized = tmp_path / "oversized.png"
    Image.new("RGB", (3000, 2000), (230, 228, 224)).save(oversized)
    p = render.build_payload(data, meta, oversized)
    out = tmp_path / "share.png"
    render.render_png(p, oversized, out, long_side=2000)
    img = Image.open(out)
    # Long side should be exactly 2000
    assert max(img.size) == 2000
    # Should be downscaled, so both dimensions smaller than original
    assert img.width < 3000
    assert img.height < 2000


def test_render_html_escapes_injection_attacks(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    # Craft a payload with injection attempts across several fields.
    p = render.build_payload(data, meta, basemap)
    p["title"] = "x</title><script>alert('xss')</script><title>y"
    p["legs"][0]["note"] = "broken</script><img src=x onerror=alert('xss')>"
    p["points"][0]["name"] = "<!--<script>"
    out = tmp_path / "page.html"
    render.render_html(p, "templates/map.html", out)
    html = out.read_text()
    data_line = next(line for line in html.splitlines() if "const DATA" in line)
    # The entire injected payload lands on this one line (compact JSON);
    # a positive check that it contains no raw '<' at all, rather than the
    # narrower "no </script>" check, since any raw '<' can break out of the
    # surrounding <script> context (e.g. via a new tag).
    assert "<" not in data_line


def test_font_returns_a_font_object():
    f = render._font(20)
    assert f is not None


def test_render_png_succeeds_with_chinese_title(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    data["title"] = "罗马漫步"
    p = render.build_payload(data, meta, basemap)
    out = tmp_path / "share.png"
    render.render_png(p, basemap, out)  # must not crash
    assert out.exists()


def test_compute_bbox_covers_point_and_leg_geometry():
    # Reference vector from the polyline spec: decodes to points well
    # outside the two endpoints below.
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    data = {
        "points": [
            {"id": "p1", "lat": 38.0, "lon": -120.0},
            {"id": "p2", "lat": 38.1, "lon": -120.1},
        ],
        "legs": [
            {"from": "p1", "to": "p2", "mode": "car", "geometry": encoded},
        ],
    }
    minlon, minlat, maxlon, maxlat = render.compute_bbox(data)
    # The decoded geometry ranges over lat 38.5..43.252, lon -126.453..-120.2,
    # which should widen the bbox well beyond the two points' own coords.
    assert minlat <= 38.0 and maxlat >= 43.252
    assert minlon <= -126.453 and maxlon >= -120.0


def test_transit_leg_note_renders_in_svg_and_png(tmp_path):
    data, meta, basemap = fixture(tmp_path)
    data["legs"][0]["mode"] = "transit"
    data["legs"][0]["note"] = "Metro line B, ~8 min"
    p = render.build_payload(data, meta, basemap)

    out_html = tmp_path / "page.html"
    render.render_html(p, "templates/map.html", out_html)
    html = out_html.read_text()
    # The overlay SVG is built client-side by the embedded script (not
    # present as static markup in the saved file), so we check for the
    # note-halo code path this fix adds (paint-order is unique to it,
    # unlike the pre-existing marker-number <text> creation) plus the
    # note string itself, which the note-rendering branch feeds to it.
    assert "paint-order" in html
    assert "Metro line B, ~8 min" in html

    out_png = tmp_path / "share.png"
    render.render_png(p, basemap, out_png)  # must not crash
    assert out_png.exists()


def test_banner_moves_away_from_top_left_marker():
    from render import _pick_banner_anchor

    payload = {"points": [{"n": 1, "x": 30.0, "y": 30.0}]}
    # Banner at top-left would cover the marker; expect a different corner.
    anchor = _pick_banner_anchor(payload, 1.0, 300, 60, 1000, 800, 10, 12)
    assert anchor != (10, 10)
    # With no points in any corner region, top-left is preferred.
    empty = {"points": [{"n": 1, "x": 500.0, "y": 400.0}]}
    assert _pick_banner_anchor(empty, 1.0, 300, 60, 1000, 800, 10, 12) == (10, 10)
