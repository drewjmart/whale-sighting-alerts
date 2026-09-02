# Feature Spec: Historical Whale Sighting Trends & Migration Map

**Repo:** whale-sighting-alert-monitor (existing)
**Branch:** `feature/historical-sighting-trends`
**Goal:** Extend the alert monitor from reactive (notify on a sighting) to historical (trend and migration tracking across orcas, humpbacks, and gray whales), producing pivot-style tables and a geospatial map.

**Scope note:** Broadened from orcas-only to all species your existing alert monitor already tracks (orca, humpback, gray whale, and any others it currently flags). Pod-level ID (J/K/L, Bigg's/Transient) still applies specifically to orcas; humpback and gray whale sightings will be tracked by species and, where available, individual ID (many humpbacks are individually catalogued by fluke pattern) rather than pod.

---

## Current Status

**Not deployed — local only.** Everything in this update (ingestion, storage, dashboard, Discord command) runs on your own machine right now. Nothing is hosted or publicly accessible. Deployment (making the dashboard reachable from your phone/browser away from your PC) is a separate, later step — see §7a Phase 2 — not part of this PR.

**Blocked item: Acartia API token.** Registered at acartia.io; awaiting admin approval before a Bearer token is issued (see §2 and CONTRIBUTING.md in salish-sea/acartia for why this is a manual approval step, not instant self-serve).

**This does NOT block the rest of the build.** Everything except authenticated Acartia calls (historical/trusted endpoints) can be built and tested now:
- Acartia's unauthenticated `GET /sightings/current` endpoint works with no token (last 7 days of data) — use this to build and test the client and normalization logic today
- Orca Network archive, salmon (Albion/Bonneville), NOAA tides, and moon phase all need no Acartia dependency at all
- Local dashboard and Discord command can be fully built and tested without the token

**When the token arrives:** swap it into the existing `acartia_client.py` (already designed to accept an optional Bearer token param — see §3) and this becomes commit #17 in the sequence, not a blocker on anything that came before it.

---

## 1. Problem / Motivation

The current monitor tells you a sighting happened right now. It has no memory beyond that. This feature adds a persistent store and analysis layer so patterns become visible: which species and pods visit which locations, how timing has shifted season to season, and how personal outings correlate with actual presence.

## 1a. Scope split: Alerts vs. Tracker

This PR changes two related but distinct things, and they should not be conflated in the code:

**Live alerts (push notifications)** — currently unfiltered by location; the monitor alerts on any sighting in its source feeds regardless of where it occurred. This PR adds a **geographic filter** so push notifications only fire for sightings within a West Seattle radius (default: ~8mi covering Alki Point, Emma Schmitz Overlook, and Lincoln Park — tune this once live and adjust in config, not hardcoded). This is a small, contained change to the existing alert logic.

**Historical tracker (query-on-demand)** — the new feature this spec primarily covers. This should have **no geographic restriction** — it stores and lets you query sightings anywhere in Washington waters, at any time. The map/pivot views need a **location filter parameter** (not just the existing date-range filter), so you can, for example, pull up San Juan Island activity while actually visiting, without that data ever having triggered a push notification.

Practically: the alert filter and the tracker's location query use the same underlying coordinate data, but they're separate code paths with separate purposes. Don't build one geographic filter and reuse it for both — the alert filter is a hard boolean gate ("should this notify me"), while the tracker's location query is an interactive parameter ("show me this region").

## 2. New Data Sources

| Source | What it adds | Access |
|---|---|---|
| Orca Network historical archive | Backfill of sightings beyond the live RSS feed you already parse | Same site, archive pages instead of live feed |
| Acartia API (acartia.io) | Structured, queryable Salish Sea marine mammal location data | Registration requires admin approval before you get a token — no instant self-serve. **Build against the unauthenticated `GET /sightings/current` endpoint first** (returns the last 7 days, all species/providers/trust levels, no auth needed) so the client and normalization logic can be built and tested now. Swap in the authenticated endpoints once approved — same client, just add the `Authorization: Bearer <token>` header. |
| Center for Whale Research / Orca Conservancy pod ID guides | Reference data to normalize free-text orca pod mentions ("J & L pods, Whidbey Island") into structured pod codes | No API — used to build a static lookup/normalization table |
| Happywhale / individual humpback fluke ID catalogs | Optional reference for individually-catalogued humpbacks, if you want ID-level (not just species-level) tracking | No API for scraping; manual/reference use only — treat as stretch, not day-one scope |
| Albion test fishery Chinook CPUE (DFO) + Bonneville Dam adult passage counts | Daily Chinook salmon abundance — a real, published predictor of SRKW presence at the pod level | Public data, no account/key required. Build ingestion independently from these public sources rather than referencing salish-sea/orca-salmon's implementation (see §9 Attribution note). |
| NOAA CO-OPS Tide Predictions API | Tide state as a secondary modifier on salmon/foraging behavior near constricted passages | Public API, no key required |
| Moon phase (computed, not fetched) | Experimental/exploratory column only — no established research link to SRKW presence; included to test the hypothesis honestly, not as a relied-upon feature | Computed via `astral` (already a dependency) or `ephem`, no external data source needed |

**Known nuance:** most source text names pods informally (e.g. "J pod," "Bigg's/Transients"). Normalization logic will need a lookup table and fallback category ("Unknown/Unconfirmed") rather than assuming every record cleanly resolves.

**Feature hierarchy — be explicit about this in the README:**
1. **Salmon abundance (Chinook CPUE)** — a strong, evidence-backed predictor of **orca** presence specifically at a pod level (multiple long-term studies tie SRKW habitat use to Fraser River Chinook returns). This feature does **not** apply to humpback or gray whale sightings — their diets are krill/small fish (humpback) and benthic amphipods (gray whale), not salmon. Keep this correlation scoped to orca records only; don't let it bleed into cross-species analysis where it has no evidentiary basis.
2. **Tide state** — a secondary modifier, relevant across species since tide-driven current and prey behavior affects foraging opportunity broadly, not just for orcas.
3. **Moon phase** — flagged explicitly in the README and in code (e.g. a column prefixed `experimental_`) as an unproven, exploratory variable across all species. No species-specific research supports it. Keep it in its own analysis section.

## 3. New Components

```
whale-sighting-alert-monitor/
├── ingestion/
│   ├── acartia_client.py       # API client; works unauthenticated against /current today, accepts optional Bearer token param for /trusted and historical endpoints once approved
│   └── orca_network_archive.py # Historical archive parser (extends existing feedparser logic)
├── normalization/
│   ├── pod_resolver.py         # Free-text -> orca pod code (J/K/L/Biggs-Transient); species classifier for non-orca whales
│   └── location_geocoder.py    # Location name -> lat/lon
├── alerts/
│   └── geo_filter.py           # Hard boolean gate for push notifications: is this sighting within the West Seattle radius?
├── storage/
│   ├── schema.sql              # SQLite schema
│   └── db.py                   # Read/write layer
├── analysis/
│   ├── pivots.py                # pandas pivot tables: by pod/month, by location, by year
│   └── location_query.py       # On-demand region lookup: "what's active near San Juan Island right now" — no geographic restriction
├── viz/
│   ├── map.py                  # folium map, color-coded by pod, filterable by BOTH date range and location/region
│   └── trends.py                # plotly/matplotlib trend charts
├── discord/
│   └── whale_command.py        # /whales [region] slash command — current activity summary, reuses Acartia /current
│   # CONFIRMED: existing alert integration is webhook-only. Webhook stays as-is for push alerts — do not
│   # migrate it. This command requires a SEPARATE, ADDITIVE bot application (with applications.commands scope,
│   # invited alongside the webhook) purely to handle the slash command. Two integrations coexist by design.
├── dashboard/
│   ├── app.py                  # Flask/FastAPI app — local-only for now, no deployment in this PR
│   ├── templates/               # dashboard pages: current activity, historical map, pivot views
│   └── static/
│   # Build and test entirely via localhost (`flask run` / `uvicorn app:app --reload`). Deployment to Render
│   # is a separate, later step (see §7a Phase 2) — don't couple the two.
├── tests/
│   ├── test_pod_resolver.py
│   ├── test_acartia_client.py
│   └── test_pivots.py
└── README.md (updated)
```

## 4. Data Schema (SQLite)

**Confirmed Acartia field mapping** (from Typehuman/SSEMMI CONTRIBUTING.md, real sample response): Acartia returns `type` (species, e.g. `"Humpback"`), `latitude`/`longitude`, `created` (timestamp), `trusted` (trust flag), `data_source_entity`, `data_source_witness`, and `data_source_comments` — this last field is likely where free-text orca pod mentions live, confirming the pod-resolver needs to parse comments, not just a dedicated pod field. Map these into the schema below during ingestion.

```sql
CREATE TABLE sightings (
    id INTEGER PRIMARY KEY,
    sighting_date DATE NOT NULL,
    species TEXT NOT NULL,       -- from Acartia 'type', or Orca Network parsing; 'orca', 'humpback', 'gray_whale', etc.
    pod_code TEXT,               -- orca only, parsed from comments/raw text: 'J', 'K', 'L', 'BIGGS_TRANSIENT', 'UNKNOWN'; NULL for non-orca species
    individual_id TEXT,          -- optional, e.g. humpback fluke ID if known
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    trusted BOOLEAN,             -- from Acartia 'trusted' flag where available; NULL for sources without a trust concept
    source TEXT NOT NULL,        -- 'orca_network', 'acartia'
    raw_text TEXT,                -- original report/comments text, for auditability and pod-resolver input
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE environmental_context (
    sighting_id INTEGER REFERENCES sightings(id),
    chinook_cpue REAL,                  -- orca records only; NULL for other species
    tide_height_ft REAL,                -- NOAA CO-OPS, applies across species
    tide_state TEXT,                    -- 'flood', 'ebb', 'slack'
    experimental_moon_phase REAL        -- explicitly flagged as unproven/exploratory, all species
);
```

## 5. Reuse Existing Patterns

Your solutions-architect review already flagged source-health monitoring (`consecutive_zero_runs`, `last_success`, `STALE_THRESHOLD_HOURS`) for the live alert. Apply the same pattern to both new ingestion sources so a silently-broken historical feed doesn't quietly corrupt your trend data.

## 6. Suggested Commit Sequence

For a PR history that reads as real incremental development rather than one large drop:

1. `feat: add Acartia API client against unauthenticated /current endpoint`
2. `feat: add Orca Network historical archive parser`
3. `feat: add SQLite schema and storage layer`
4. `feat: add pod name normalization with lookup table`
5. `feat: add Chinook CPUE ingestion (Albion test fishery)`
6. `feat: add NOAA tide data ingestion`
7. `feat: add experimental moon phase column (flagged, exploratory)`
8. `feat: add pivot table analysis functions`
9. `feat: add on-demand location query (region lookup, e.g. San Juan Island)`
10. `feat: add West Seattle geo-filter for push alerts (config-driven radius)`
11. `feat: add folium map visualization by pod, filterable by date and location`
12. `feat: add trend charts over time`
13. `feat: add /whales Discord slash command for remote current-activity check`
14. `feat: add local Flask/FastAPI dashboard (localhost only, wraps map + pivots + region query)`
15. `docs: update README with historical trends feature, feature hierarchy, and Phase 2 roadmap`
16. `feat: add CLI entry point to regenerate reports`
17. `feat: add Acartia Bearer auth + historical/trusted endpoints (once approved)` — *slot in whenever the token arrives; doesn't need to happen in sequence*

## 7. Acceptance Criteria

- [ ] Ingests at least one full season of historical sightings from both sources, across orca, humpback, and gray whale records, covering all Washington waters (not just West Seattle)
- [ ] Orca pod names normalized into consistent categories with an explicit "unresolved" bucket (no silent misclassification); non-orca species normalized by species name only
- [ ] Produces a pivot table: orca sightings by pod × month
- [ ] Produces a pivot table: sightings by species × month (all species)
- [ ] Produces a pivot table: sightings by location × species
- [ ] Can query activity for any WA region on demand (e.g. "what's near San Juan Island right now"), independent of home location
- [ ] Produces a map showing sighting locations, color-coded by species (orca sightings further distinguishable by pod), filterable by BOTH date range and location/region
- [ ] Push notifications only fire for sightings within a configurable West Seattle radius (default ~8mi covering Alki/Emma Schmitz/Lincoln Park); this filter does not affect what the tracker can query
- [ ] `/whales [region]` Discord command returns current activity (using Acartia's `/current` data) so activity is checkable remotely from your phone, not just from a PC
- [ ] Local dashboard (Flask/FastAPI) runs via `localhost`, wrapping the map, pivot tables, and region query in a browsable web UI, fully testable before any deployment decision is made
- [ ] Chinook CPUE joined only to orca records as environmental context; tide data joined across all species
- [ ] Moon phase included but clearly labeled `experimental_` in schema, code, and README — never presented as a validated predictor
- [ ] Source-health monitoring applied to all new ingestion sources
- [ ] Unit tests for normalization logic, API client, and the alert geo-filter (confirm it correctly includes/excludes boundary cases)
- [ ] README updated with feature description, feature hierarchy (salmon [orca-only] > tide > experimental moon phase), and a sample screenshot

## 7a. Phase 2 (documented, not built in this PR)

Deploy the local dashboard (once built and tested) to Render's free tier for real mobile browser access. Deliberately split from the dashboard build itself:

- **This PR:** build and test the dashboard entirely locally (`flask run` / `uvicorn`, `localhost`). No deployment risk, no hosting decisions needed yet — just get the app itself working and verified on your own machine.
- **Phase 2 (separate, later):** connect the repo to Render and deploy. Render is the only platform with a genuine permanent free tier as of 2026 (Railway and Fly.io both dropped theirs) — the trade-off is a cold start (~60 seconds) after 15 minutes of inactivity, worth knowing before relying on it mid-trip.

Splitting it this way means the harder, more valuable part (the actual dashboard) gets built and proven now, and deployment becomes a low-risk, mechanical step whenever you're ready for it, rather than a blocker on getting started.

---

## 8. GitHub Issue Template (open this first)

```
Title: Add historical whale sighting trend analysis and migration map

## Summary
Extend the monitor from live alerting to historical analysis: ingest
past sightings (orca, humpback, gray whale) from Orca Network's archive
and the Acartia API, normalize species and orca pod identity, and produce
pivot-table trend views plus a geospatial map of activity over time.
Also adds a geographic filter to existing push alerts (West Seattle only)
while keeping the historical tracker queryable for any WA region.

## Motivation
Currently the monitor has no memory and no location filtering — every
sighting anywhere triggers a push notification. This adds persistence
and analysis so long-term patterns become visible across all species,
narrows push alerts to a home region (West Seattle) so they stay
relevant day to day, and lets the tracker answer on-demand questions
like "what's active near San Juan Island right now" when traveling.

## Scope
See attached spec doc for schema, component breakdown, and acceptance
criteria.

## Out of scope (for this PR)
- Predictive/forecasting models (potential follow-up)
- Individual humpback fluke ID tracking (stretch goal, not day-one)
```

## 9. Attribution Note

`salish-sea/orca-salmon` is a similar existing dashboard (Chinook counts + SRKW occurrence). It's useful as a reference for *what's possible*, not as source material:

- Do **not** have Claude Code read or adapt their source code — build the Albion/Bonneville ingestion independently from the public data sources directly.
- **Do** credit data sources in the README under a "Data Sources" section — standard practice for any project built on public data, distinct from code attribution. For Acartia specifically, credit the cooperative itself (acartia.io) and its founding data providers, Orca Network and Orcasound, since Acartia's own about page names both as original contributors to the effort.
- If curiosity gets the better of you and you do look at their repo, check its `LICENSE` file first — no license file means no reuse rights are granted even though the code is publicly visible.

**Suggested README credit line:**
> Whale sighting data provided by [Acartia](https://acartia.io), a decentralized data cooperative for the Salish Sea, with founding data contributions from [Orca Network](https://orcanetwork.org) and [Orcasound](https://orcasound.net). Salmon abundance data from the Albion test fishery (DFO) and Bonneville Dam adult passage counts. Tide data from NOAA CO-OPS.

## 10. PR Description Template (use when opening the PR)

```
## What
Adds historical sighting ingestion (Orca Network archive + Acartia API)
across orca, humpback, and gray whale species, species/pod normalization,
SQLite storage, pivot-table trend analysis, and a folium-based migration map.

## Why
Closes #<issue-number>. Turns the monitor into a historical tracking tool
in addition to a live alerter, enabling migration/habit analysis by pod.

## How to test
1. `pip install -r requirements.txt`
2. Set `ACARTIA_API_KEY` in `.env`
3. Run `python -m ingestion.run_backfill --season 2025`
4. Run `python -m viz.map` to generate `map.html`
5. Run `pytest tests/`

## Notes
- Pod normalization defaults unresolved names to `UNKNOWN` rather than guessing
- Source-health checks reuse the existing pattern from the live alert module
```
