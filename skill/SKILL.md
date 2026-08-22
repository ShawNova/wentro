---
name: wentro
description: Turn a finished trip into a shareable itinerary map (post-trip recap, not planning). Use when the user wants to create, update, or share a route map of places they visited — start, waypoints, destination, transport modes. Triggers on "行程图", "旅行路线图", "itinerary map", "trip map", "travel recap", "wentro".
---

# Wentro — post-trip itinerary maps

Turn a finished trip into (1) an interactive map artifact and (2) a static
PNG share image. All network work happens conversation-side via the scripts
in `scripts/` — the published artifact makes no external requests.

**Source of truth:** one JSON file per itinerary. Data directory:
`./itineraries/` if it exists in the working directory, else
`~/.wentro/itineraries/`. Never regenerate from chat memory when the file
exists — load it.

## Input contract

Minimum viable input: a region plus two or more places, in any language.
If input is incomplete, do NOT guess — show this template:

> - Region (city or country): …
> - Places in visit order: …
> - How you moved between them (walking by default): …

## Parse & normalize (your job, not the scripts')

1. Validate: region present; ≥2 points; modes within foot/bike/car/transit.
2. Per place, build a geocoding `query`: fix typos, translate to the local
   language or English, append city context. Keep the user's wording as `name`.
3. Mode parsing — recognize three scopes with precedence
   per-leg > exception ("taxi to the airport, rest walking") > trip default
   ("all on foot"). Write the resolved mode on EVERY leg. If no mode was
   stated at any scope, use `foot` and flag the assumption in your reply.

## Pipeline (run from the repo root, or substitute the skill directory)

1. Geocode each point (~1 s per call — Nominatim rate limit):
   `python3 skill/scripts/geocode.py --query "Colosseum, Rome" --region "Rome, Italy"`
   → `{bounded, candidates:[{display_name, lat, lon, ...}]}`.
   Pick the best candidate; if ambiguous or `bounded: false`, show the top
   candidates and ask. Store lat/lon/resolved on the point.
2. Write the JSON; `common.save_itinerary` validates the chain invariant.
3. Coherence gate:
   `python3 skill/scripts/validate.py --itinerary itineraries/<slug>.json`
   Exit 1 = outlier hard error → re-geocode the flagged point; if it still
   fails, STOP and ask the user. Warnings → confirm with the user before
   proceeding. Never render a map with a known-suspect point.
4. Route each non-transit leg (lat,lon order; vias between endpoints):
   `python3 skill/scripts/route.py --mode foot --coords "41.8902,12.4922;41.8925,12.4853"`
   → store geometry/distance_m/duration_s on the leg. On RuntimeError:
   keep geometry null (renders as dashed approximate) and tell the user.
   Transit legs: no routing; write a human `note` ("Metro line B, ~8 min").
5. Basemap (bbox = min/max of all point coords; script pads it):
   `python3 skill/scripts/tiles.py --bbox "12.4731,41.8902,12.4922,41.9009" --out /tmp/wentro-map.png --meta-out /tmp/wentro-meta.json`
6. Render:
   `python3 skill/scripts/render.py --itinerary itineraries/<slug>.json --basemap /tmp/wentro-map.png --meta /tmp/wentro-meta.json --template templates/map.html --out-html /tmp/wentro-page.html --out-png itineraries/<slug>.png`
7. Publish `/tmp/wentro-page.html` as an artifact. If the itinerary has an
   `artifact_url`, pass it as `url` so the SAME link updates. Store the
   returned URL in the JSON. Send the PNG to the user as a file.
8. Reply with: artifact link, the resolved-name list for eyeballing, and
   any assumptions or warnings.

## Update / delete

- Load the JSON (never rebuild from memory). Apply the edit:
  - add point → insert into `points`, split the leg, re-route both halves;
  - wrong route → derive `via` coordinate(s) from the user's description,
    add to that leg's `via`, re-route that leg only;
  - wrong point → replace/remove; merge adjacent legs on removal, re-route.
- Re-run steps 3–8. Tiles can be reused when the bbox is unchanged.
- The chain invariant is enforced on every save — if it trips, fix the
  legs list, don't bypass validation.

## Etiquette

Nominatim ≤1 req/s (built into geocode.py). Tiles ≤80/build, sequential
(built into tiles.py). Don't loop these scripts aggressively.
