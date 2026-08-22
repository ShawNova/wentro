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
