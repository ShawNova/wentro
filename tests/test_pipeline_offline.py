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
