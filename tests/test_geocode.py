import geocode


def fake_search(responses):
    """Return a stub for geocode.search that pops canned responses."""
    calls = []

    def stub(params):
        calls.append(params)
        return responses.pop(0)

    return stub, calls


ROME_REGION_HIT = [{
    "display_name": "Roma, Italia",
    "lat": "41.8933", "lon": "12.4829",
    "boundingbox": ["41.65", "42.14", "12.23", "12.85"],  # s, n, w, e
}]

COLOSSEUM_HIT = [{
    "display_name": "Colosseo, Roma, Italia",
    "lat": "41.8902", "lon": "12.4922",
    "type": "attraction", "importance": 0.9,
}]


def test_region_viewbox_reorders_bbox(monkeypatch):
    stub, _ = fake_search([list(ROME_REGION_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    assert geocode.region_viewbox("Rome, Italy") == "12.23,41.65,12.85,42.14"


def test_bounded_search_used_when_region_resolves(monkeypatch):
    stub, calls = fake_search([list(ROME_REGION_HIT), list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum", region="Rome, Italy")
    assert r["bounded"] is True
    assert r["candidates"][0]["lat"] == 41.8902
    assert calls[1]["bounded"] == 1
    assert calls[1]["viewbox"] == "12.23,41.65,12.85,42.14"


def test_falls_back_to_unbounded_when_bounded_empty(monkeypatch):
    stub, calls = fake_search([list(ROME_REGION_HIT), [], list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum", region="Rome, Italy")
    assert r["bounded"] is False
    assert len(r["candidates"]) == 1
    assert "bounded" not in calls[2]


def test_no_region_goes_straight_unbounded(monkeypatch):
    stub, calls = fake_search([list(COLOSSEUM_HIT)])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Colosseum")
    assert r["bounded"] is False
    assert len(calls) == 1


def test_empty_result_reported(monkeypatch):
    stub, _ = fake_search([[], []])
    monkeypatch.setattr(geocode, "search", stub)
    r = geocode.geocode("Xyzzynotaplace", region=None)
    assert r["candidates"] == []
