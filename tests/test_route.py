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
