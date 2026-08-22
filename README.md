# Wentro (温途)

[中文说明](README.zh-CN.md)

Wentro — retrace the journey you went. 温途——重温你走过的路。

## What it is

Wentro is a [Claude Code](https://claude.com/claude-code) skill for turning a trip you've
already taken into a map. You tell Claude, in conversation, where you went — in
whatever language you think in — and it:

- **geocodes** the real places (via [Nominatim](https://nominatim.org/)),
- **fetches real routes** between them (via the FOSSGIS public [OSRM](http://project-osrm.org/)
  instances, for walking, cycling, or driving — public transit legs don't have a free
  global routing API, so they're drawn schematically instead),
- stitches a real [OpenStreetMap](https://www.openstreetmap.org/copyright) basemap under
  the route, and
- publishes an interactive map as a Claude Artifact, plus a static PNG you can drop
  straight into a chat or a blog post.

It is deliberately **not** a trip planner. There's no search for "best things to do,"
no itinerary suggestions, no optimization. The input is always a route you already
walked (or drove, or rode) — Wentro's job is recap and sharing, not planning.

## Why the work happens conversation-side

Published Claude Artifacts run under a strict content-security policy: no outgoing
network requests, ever. That rules out fetching tiles or calling a routing API from
inside the artifact itself. So Wentro does the opposite — Claude does all the live
data work (geocoding, routing, tile fetching) *while you're talking to it*, using the
scripts in this repo, and bakes every result into one self-contained HTML page. The
published artifact never talks to the network; it doesn't need to.

## Install

The skill folder is self-contained — installing it is just copying it into place:

```bash
git clone --depth 1 https://github.com/ShawNova/wentro.git /tmp/wentro
mkdir -p ~/.claude/skills && cp -r /tmp/wentro/skill ~/.claude/skills/wentro && rm -rf /tmp/wentro
```

Nothing else to set up: on first use the skill checks for Python ≥ 3.10 and
installs its two dependencies (`requests`, `Pillow`) into `~/.wentro/venv`
automatically.

For development, clone the repo and symlink instead, so the installed skill
tracks your working tree:

```bash
git clone https://github.com/ShawNova/wentro.git
cd wentro && pip install -r requirements-dev.txt
mkdir -p ~/.claude/skills && ln -sfn "$(pwd)/skill" ~/.claude/skills/wentro
```

## Usage

Just talk to Claude about a trip. If you give incomplete information, Claude shows you
this template instead of guessing:

> - Region (city or country): …
> - Places in visit order: …
> - How you moved between them (walking by default): …

The minimum viable input is a region plus two or more places, in any language.

**Create**, mixing transport modes freely:

> I walked around Rome — Colosseum, then the Roman Forum, then Trevi Fountain,
> then took a taxi to the Pantheon, then walked to Piazza Navona.

Claude geocodes each place, routes each leg (foot for the walked legs, car for the
taxi hop), stitches the basemap, and replies with the artifact link and the resolved
place names so you can eyeball them.

**Add a point** to an existing itinerary:

> Add a stop at the Trevi Fountain gelato place right after Trevi Fountain.

Claude inserts the point, re-routes only the two legs touching it, and republishes to
the *same* artifact URL.

**Fix a route** that took a wrong turn:

> The walk from the Forum to Trevi actually went along the river, not through
> Piazza Venezia.

Claude derives a `via` correction point from your description, re-routes just that
leg, and republishes — the correction is saved in the itinerary file, so it won't
regress the next time the map is rebuilt.

**Delete a point**:

> Actually we skipped Piazza Navona.

Claude removes the point, merges its two neighboring legs into one, re-routes, and
republishes.

## Data

Every itinerary is one JSON file — the source of truth. Claude never regenerates a map
from chat memory when the file already exists; it loads and edits it. That means an
itinerary survives across sessions, and any later conversation can pick it up and keep
editing it.

Data directory resolution: `./itineraries/` in the current working directory if it
exists (useful when you're working from inside a clone of this repo), otherwise
`~/.wentro/itineraries/` (created on first use). See
[`docs/data-format.md`](docs/data-format.md) for the full field-by-field reference,
and [`examples/rome-walk.json`](examples/rome-walk.json) for a worked example.

## Etiquette & attribution

Wentro talks to shared public infrastructure run by volunteers, and follows each
service's usage policy:

- **Nominatim** — geocoding, capped at one request per second, with a descriptive
  User-Agent.
- **FOSSGIS OSRM** (`routing.openstreetmap.de`) — walking/cycling/driving routes, low
  volume, descriptive User-Agent.
- **OpenStreetMap tile servers** — basemap tiles, downloaded one at a time with a
  short pause between requests, at most 80 tiles per map build, with a descriptive
  User-Agent.

Every rendered map and PNG carries the required **© OpenStreetMap contributors**
attribution.

## Roadmap

- Photo insertion per point — the `photos` field is already reserved in the data
  model, just not rendered yet.

## License

MIT — see [LICENSE](LICENSE).
