# Itinerary data format

[中文说明](data-format.zh-CN.md)

Every itinerary is a single JSON file at `<data-dir>/<slug>.json`. It is the
source of truth: Claude loads and edits this file rather than regenerating a
map from chat memory, and any later session can pick it up. A worked example
ships at [`examples/rome-walk.json`](../examples/rome-walk.json).

## Data directory

Scripts resolve where itinerary files live with this rule, in order:

1. `./itineraries/` in the current working directory, if it exists — this is
   the case when you're working from inside a clone of this repo.
2. Otherwise, `~/.wentro/itineraries/` — the global default, created on first
   use.

## Annotated example

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

## Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `title` | string | Human-readable name for the itinerary, shown on the map and its side panel. |
| `region` | string | The declared region (city or country), e.g. `"Rome, Italy"`. Used to bias geocoding (Nominatim `viewbox`) and to check that every resolved point actually falls within it. |
| `points` | array | Ordered list of stops, first to last. See *Point fields* below. |
| `legs` | array | Ordered list of connections between consecutive points. See *Leg fields* below. |
| `artifact_url` | string \| null | The published Claude Artifact URL, or `null` before first publish. Passed back in on republish so updates land on the same URL instead of minting a new one. |
| `updated` | string | ISO date (`YYYY-MM-DD`) of the last write. Set automatically whenever the file is saved. |

## Point fields

Each entry in `points` is one stop on the trip:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable identifier for the point (e.g. `"p1"`), referenced by `legs[].from` / `legs[].to`. Unique within the itinerary. |
| `name` | string | Display name, in the user's own wording and language — never overwritten by geocoding. |
| `query` | string | The canonical geocoding query Claude built from `name`: typos fixed, translated to the local language or English, with city/region context appended. |
| `resolved` | string | The canonical address string Nominatim returned for `query`. |
| `lat`, `lon` | number | Resolved coordinates (WGS84 decimal degrees). |
| `photos` | array | **Reserved.** Not rendered in this release — see *Roadmap* in the README. Always present as an (empty) array so future versions can populate it without a schema migration. |

## Leg fields

Each entry in `legs` connects `points[i]` to `points[i+1]`:

| Field | Type | Meaning |
|---|---|---|
| `from`, `to` | string | Point ids for this leg's endpoints. Must satisfy the chain invariant below. |
| `mode` | string | One of `foot`, `bike`, `car`, `transit`. Always written explicitly — the format has no implicit default. |
| `via` | array | List of `[lat, lon]` correction points for non-transit legs (empty by default). See *`via` semantics* below. Omitted for `transit` legs. |
| `geometry` | string \| null | OSRM route geometry, polyline5-encoded (OSRM's default encoding). `null` means no route could be computed — the map falls back to a straight dashed line marked as approximate. Omitted for `transit` legs. |
| `distance_m` | number \| null | Route distance in meters, from OSRM. Omitted for `transit` legs. |
| `duration_s` | number \| null | Route duration in seconds, from OSRM. Omitted for `transit` legs. |
| `note` | string | Human-readable description for a `transit` leg (e.g. `"Metro line B, ~8 min"`), since transit legs aren't routed. Only present on `transit` legs. |

### Mode values

`foot`, `bike`, and `car` are routed through the FOSSGIS OSRM instances
(`routed-foot`, `routed-bike`, `routed-car`) and get real route geometry.
`transit` legs are never routed — there's no free global public-transit
routing API — and are rendered as a schematic dashed line labeled with
`note` instead.

### `via` semantics

`via` holds user-supplied correction coordinates for a leg whose routed path
didn't match what actually happened (OSRM took a different street, missed a
detour, etc.). When present, `route.py` routes through these points in order
between `from` and `to`. Corrections are persisted in the file specifically
so that regenerating the map later — after adding a point elsewhere, say —
never regresses a previously-fixed leg back to the wrong route.

## Chain invariant

`legs` must form a single chain that visits `points` in array order:

- `legs[i].from == points[i].id`
- `legs[i].to == points[i + 1].id`
- there are exactly `len(points) - 1` legs.

This is what makes an itinerary one continuous route rather than a bag of
disconnected points. Scripts validate the invariant on every load and every
save (`common.validate_chain`) and refuse to render — or write — a file that
breaks it. Edits that change the point order (insert, delete) must update the
adjacent legs in the same operation so the chain stays intact; see the
*Update / delete* workflow in `skill/SKILL.md`.
