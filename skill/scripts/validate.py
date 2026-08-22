"""Coherence checks: outlier points and implausible legs.

Numeric checks live here so they run identically every time
("scripts compute, Claude judges").
"""
import argparse
import json
import sys

from common import haversine_km, load_itinerary, median_center

# Hard-error distance from the itinerary's median center, by the most
# permissive mode present in the trip.
OUTLIER_KM = {"foot": 30, "bike": 100, "car": 500, "transit": 500}
# Per-leg crow-flies distances that trigger a confirmation warning.
LEG_WARN_KM = {"foot": 15, "bike": 60}


def check(data):
    errors, warnings = [], []
    pts = {p["id"]: p for p in data["points"]}
    modes = {leg["mode"] for leg in data["legs"]}
    threshold = max(OUTLIER_KM[m] for m in modes)

    latlons = [(p["lat"], p["lon"]) for p in data["points"]]
    if len(latlons) >= 3:
        center = median_center(latlons)
        for p in data["points"]:
            d = haversine_km(p["lat"], p["lon"], *center)
            if d > threshold:
                errors.append(
                    f"outlier: {p['id']} ({p['name']}) is {d:.0f} km from the "
                    f"itinerary center (threshold {threshold} km)"
                )

    for i, leg in enumerate(data["legs"]):
        a, b = pts[leg["from"]], pts[leg["to"]]
        d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        warn = LEG_WARN_KM.get(leg["mode"])
        if warn and d > warn:
            warnings.append(
                f"leg {i} ({a['name']} -> {b['name']}): {d:.0f} km as the "
                f"crow flies is long for mode '{leg['mode']}'"
            )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--itinerary", required=True)
    args = ap.parse_args()
    report = check(load_itinerary(args.itinerary))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
