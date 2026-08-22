from validate import check


def base():
    return {
        "title": "T",
        "region": "Rome, Italy",
        "points": [
            {"id": "p1", "name": "A", "lat": 41.8902, "lon": 12.4922},
            {"id": "p2", "name": "B", "lat": 41.8925, "lon": 12.4853},
            {"id": "p3", "name": "C", "lat": 41.9009, "lon": 12.4833},
        ],
        "legs": [
            {"from": "p1", "to": "p2", "mode": "foot", "via": []},
            {"from": "p2", "to": "p3", "mode": "foot", "via": []},
        ],
    }


def test_clean_itinerary_passes():
    r = check(base())
    assert r == {"ok": True, "errors": [], "warnings": []}


def test_outlier_is_hard_error():
    data = base()
    # Milan in a Rome walking itinerary: ~475 km away.
    data["points"][2].update(lat=45.4642, lon=9.19)
    r = check(data)
    assert not r["ok"]
    assert any("outlier" in e for e in r["errors"])


def test_outlier_threshold_scales_with_mode():
    data = base()
    data["points"][2].update(lat=45.4642, lon=9.19)
    for leg in data["legs"]:
        leg["mode"] = "car"  # 500 km threshold: Milan is fine by car
    r = check(data)
    assert r["ok"]


def test_long_foot_leg_warns():
    data = base()
    data["points"][1].update(lat=42.05, lon=12.4922)  # ~18 km north
    r = check(data)
    assert r["ok"]  # warning, not error
    assert any("long for mode 'foot'" in w for w in r["warnings"])


def test_two_points_skip_outlier_check():
    data = base()
    data["points"].pop()
    data["legs"].pop()
    assert check(data)["ok"]
