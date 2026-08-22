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
