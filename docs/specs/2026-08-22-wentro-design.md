# Wentro (温途) — Design Document

**Date:** 2026-08-22
**Status:** Approved

## Overview

Wentro ("went" + route; 温途, *wēntú*, "re-warming the journey") is an
open-source Claude Code skill that turns a finished trip into a shareable
itinerary map. The user describes a route they walked (or drove/cycled) in
conversation; Claude geocodes the real places, fetches real navigation
routes, and publishes a self-contained interactive map as a Claude Artifact.

Tagline: *Wentro — retrace the journey you went. 温途——重温你走过的路。*

## Goals

- **Post-trip sharing, not planning.** Input is a route the user already
  took: one origin, ordered waypoints, one destination, plus a transport
  mode per leg.
- **Real geography.** Real coordinates (Nominatim), real route geometry
  (OSRM), real basemap tiles (OpenStreetMap) — not schematic sketches.
- **Conversational CRUD.** Create, update (add points / correct routes),
  and delete points by talking to Claude; the artifact URL stays stable
  across updates.
- **Cross-session durability.** Each itinerary is a JSON file on disk —
  the source of truth. Any later session can reload and edit it.
  Resolution order: `./itineraries/` in the current working directory if
  it exists (working inside the repo), else `~/.wentro/itineraries/`
  (global default, created on first use).

## Non-goals (current release)

- Trip planning, suggestions, or optimization.
- Real public-transit routing (no free global API); transit legs are
  rendered schematically.
- Photo insertion (reserved in the data model, on the roadmap).
- Multi-day structure: one itinerary = one route chain. Multi-day trips
  are simply multiple itineraries.

## Architecture

The hard constraint: published Artifacts run under a strict CSP — no
external network requests (no tile servers, no routing APIs). Therefore
**all live data acquisition happens conversation-side**, executed by
Claude through the skill's scripts. The artifact is a fully static,
self-contained HTML page with everything baked in.

Pipeline (orchestrated by Claude per SKILL.md):

1. **Parse** user input → draft itinerary JSON.
2. **Geocode** each point via Nominatim, biased by the itinerary region;
   ambiguous hits are surfaced to the user as a candidate list.
3. **Route** each leg via the public OSRM instances run by FOSSGIS at
   `routing.openstreetmap.de` (profiles: `routed-foot`, `routed-bike`,
   `routed-car` — the official OSRM demo server only serves driving),
   honoring user-supplied `via` correction points. Transit legs skip OSRM.
4. **Tiles**: compute the route bounding box + padding, choose a zoom
   level that fits ~1200 px wide (tile count capped), download OSM tiles,
   stitch into one PNG, embed as a data URI.
5. **Render** the HTML from a template: stitched basemap, SVG route
   overlay, numbered markers, itinerary side panel.
6. **Publish** as an Artifact; store the URL back into the JSON.

Updates re-run only the affected stages (e.g. adding one point re-routes
two legs; tiles are re-fetched only if the bounding box changed) and
republish to the same artifact URL.

## Input contract & validation

**Input guidance.** When invoked with incomplete input, Claude does not
guess — it shows a compact template: region; ordered list of places (any
language); default transport mode; optional per-leg overrides (mode,
note). Minimum viable input: a region plus two or more places. The README
documents the same contract with examples (EN and zh-CN).

**Model-side normalization (Claude's job).** Nominatim accepts
multilingual queries, but resolution is far more reliable in the place's
local language or English. Before geocoding, Claude:

1. validates completeness — region present, ≥2 points, every mode within
   {foot, bike, car, transit};
2. turns each user-supplied place name into a canonical geocoding
   `query` — typos corrected, any language translated to the local
   language or English, city/region context appended. The user's original
   wording is preserved as the display `name`.

**Deterministic checks (scripts' job).** `geocode.py` passes a
region-derived `viewbox` with `bounded=1` so search prefers in-region
hits, and returns top-N candidates with coordinates and address.

**Coherence validation — after geocoding, before routing:**

- *Outlier check:* compute the median center of resolved points; a point
  farther out than a mode-aware threshold (30 km for a walking itinerary)
  is a hard error — re-geocode bounded, and if it still lands outside,
  stop and report the candidates to the user. Never render a map with a
  known-suspect point.
- *Leg plausibility:* per-mode warning thresholds (foot > 15 km,
  bike > 60 km per leg) trigger an explicit user confirmation.
- *Region consistency:* each resolved address must match the declared
  region; mismatches are challenged, not silently accepted.

Division of labor: **scripts compute, Claude judges.** Numeric checks
live in scripts so they run identically every time; semantic arbitration
— which candidate is right, whether an outlier is a typo or a genuine
day trip — stays with the model and the user.

## Repository layout

```
wentro/
├── README.md / README.zh-CN.md   # English primary, Chinese mirror
├── LICENSE                       # MIT
├── skill/
│   ├── SKILL.md                  # the C/U/D workflow (English)
│   └── scripts/
│       ├── geocode.py            # Nominatim search w/ region bias
│       ├── route.py              # OSRM routing w/ via-points
│       ├── tiles.py              # OSM tile fetch + stitch → data URI
│       └── render.py             # JSON + template → final HTML
├── templates/map.html            # render template
├── requirements.txt              # requests, Pillow
├── examples/rome-walk.json       # committed sample itinerary
├── itineraries/                  # user data, gitignored
└── docs/                         # data-format.md etc., EN + zh-CN
```

Installation: clone, then copy or symlink `skill/` to
`~/.claude/skills/wentro/` (one-liner in the README).

## Data model

`itineraries/<slug>.json` is the source of truth:

```json
{
  "title": "Classic Rome Walk",
  "region": "Rome, Italy",
  "points": [
    {
      "id": "p1",
      "name": "斗兽场",
      "query": "Colosseum, Rome",
      "resolved": "Colosseo, Roma",
      "lat": 41.8902,
      "lon": 12.4922,
      "photos": []
    }
  ],
  "legs": [
    {
      "from": "p1", "to": "p2", "mode": "foot",
      "via": [],
      "geometry": "<polyline5-encoded geometry (OSRM default)>",
      "distance_m": 850, "duration_s": 640
    },
    {
      "from": "p2", "to": "p3", "mode": "transit",
      "note": "Metro line B, ~8 min"
    }
  ],
  "artifact_url": null,
  "updated": "2026-08-22"
}
```

- `via`: user route corrections, persisted so regeneration never regresses
  to a wrong route.
- `photos`: reserved, not rendered in this release.
- Point `name` keeps the user's language; `query`/`resolved` hold the
  geocoding request and canonical result.
- **Chain invariant:** `legs` must form a single chain visiting `points`
  in array order (`legs[i].from == points[i].id`,
  `legs[i].to == points[i+1].id`). Scripts validate this on every read
  and write and refuse to render an inconsistent file.

## Workflows

**Create.** User supplies region, ordered points, per-leg modes →
normalization and coherence validation (see *Input contract &
validation*) → full pipeline → reply with the artifact link plus the
list of resolved place names, flagging any warnings inline.

**Update — add point.** Insert into `points`, split the affected leg,
re-route the two new legs, re-render, republish same URL.

**Update — route correction.** User points out a wrong segment ("should
follow the river"); Claude derives one or more `via` coordinates, re-routes
that leg, republishes.

**Delete point.** Remove the point, merge its two adjacent legs into one,
re-route, republish.

## Rendering

- Stitched OSM basemap as the background layer inside a pan container;
  CSS zoom up to ~2.5×.
- SVG overlay: route polylines colored per mode (foot / bike / drive),
  dashed lines with a label for transit legs; numbered circular markers.
- Side panel: ordered itinerary list with per-leg mode, distance, and
  duration, plus totals; clicking an entry highlights the marker.
- Theme-aware (light/dark per Artifact rules); fully self-contained,
  under the 16 MB artifact limit (tile budget enforced by `tiles.py`).
- Required OSM attribution rendered on the map.

## External services & etiquette

| Service | Use | Etiquette |
|---|---|---|
| Nominatim | geocoding | descriptive User-Agent, ≤1 req/s |
| FOSSGIS OSRM (`routing.openstreetmap.de`) | foot/bike/car routes | descriptive UA, low volume |
| OSM tile server | basemap tiles | descriptive UA, ≤2 concurrent, ≤80 tiles per build |

## Error handling

- Geocode miss → ask the user for a more specific name/address.
- Ambiguous geocode → present top candidates, let the user pick.
- OSRM unreachable/no route → tell the user; fall back to a straight
  dashed line marked as approximate.
- Tile download failure → retry, then drop one zoom level.

## Dependencies

- Python ≥ 3.10; third-party packages limited to `requests` (HTTP) and
  `Pillow` (tile stitching), pinned in `requirements.txt`.
- README installation covers: clone → `pip install -r requirements.txt`
  → link `skill/` into `~/.claude/skills/wentro/`.

## Conventions

- Code, comments, SKILL.md, commit messages: English.
- README and docs: English primary with `*.zh-CN.md` mirrors.
- License: MIT.

## Roadmap

- Photo insertion per point (field already reserved).
- Static image export of the map for chat-app sharing.
