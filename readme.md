# Whale Sighting Alert Automation

A Python monitor that watches for whale sighting reports near West Seattle
and sends a digest the moment something new shows up, so there's no need
to manually check multiple sources throughout the day. Built entirely
self-directed after noticing a manual, repetitive task worth automating.

**Stack:** Python, feedparser, requests, BeautifulSoup4, smtplib (SSL),
astral (sunrise/sunset), Discord webhooks. Runs every 30 minutes via
Windows Task Scheduler.

## Recent Updates

### Historical Whale Sighting Trends & Migration Map (Added September 2026)
Extended the monitor from live-only alerting to historical trend analysis
and geospatial tracking across orcas, humpbacks, and gray whales.

- Ingests historical sightings from the Orca Network archive and the
  Acartia API (Salish Sea data cooperative) — 4,176 verified records
  spanning March–September 2026
- Normalizes orca pod identity (J/K/L, Bigg's/Transient) from free-text
  reports; tracks other species by name
- Correlates orca presence with Chinook salmon abundance (Albion test
  fishery, Bonneville Dam), based on published research tying SRKW
  habitat use to salmon returns — not applied to other species
- Adds tide state as a secondary environmental factor across species
- Includes an experimental (unvalidated) moon phase column, clearly
  flagged as exploratory
- Push alerts now scoped to a configurable West Seattle radius; the
  historical tracker itself is unrestricted and queryable for any
  Washington region on demand
- Local dashboard (Flask/FastAPI) and a `/whales` Discord slash command
  for checking activity remotely — currently local-only by design,
  hosted deployment deferred pending confirmation of Acartia's data
  redistribution guidelines

Data sources: [Acartia](https://acartia.io), with founding contributions
from [Orca Network](https://orcanetwork.org) and
[Orcasound](https://orcasound.net). Salmon data from the Albion test
fishery (DFO) and Bonneville Dam. Tide data from NOAA CO-OPS.

See [PR #1](../../pull/1) for full implementation details.

## Sources

The monitor currently aggregates from two RSS feeds:

- **West Seattle Blog** — main site feed, not the dedicated whale-category
  feed (the category feed was found to silently lag behind the main one —
  see the bug writeup below for the full story).
- **OrcaSound news** — blog/news feed.

*A third source, Orca Network's "recent sightings" page, was originally
part of the design and scraped via a CSS selector. Orca Network relaunched
their site and no longer publishes a scrapeable sightings page — sightings
now route through a private Facebook group that isn't reliably scrapeable
without login. That source is disabled rather than worked around, in
keeping with the same compliance-first approach used in the job search
digest project: if a source can't be accessed cleanly, it's dropped, not
circumvented.*

## Dedup and delivery

Keyword match (whale, orca, humpback, pod names) against title and body
text, then a JSON state file tracking seen URLs, trimmed to the last 2,000
entries so it doesn't grow unbounded. A small exclusion list also strips
out known false-positive phrases — like "Whale Tail Park," an actual West
Seattle playground — that would otherwise trigger on a species word
appearing inside an unrelated proper noun.

Notifications go out through two parallel, independently-failing channels:

- A plain-text and HTML digest email over SMTP_SSL.
- A Discord webhook posting to a private, single-user server.

If either channel fails, it logs the error and the other still goes
through — a delivery failure in one channel can't block the other. Per-source
error handling means one feed failing doesn't block the rest either.

**Why two channels, not just email.** Email is reliable but not immediate
enough to physically get to a viewpoint in time. Discord was added
specifically because a private, single-user server sidesteps a real
platform limitation: Discord's API doesn't support webhooks in actual DMs,
only in server channels. A free private server with one channel gets
DM-like privacy without needing a full bot (registered app, OAuth flow, bot
token).

## Daylight-only filtering

Calculates today's sunrise and sunset for West Seattle using the `astral`
library and exits immediately if the script runs outside daylight hours —
no point alerting on a sighting nobody can photograph in the dark. Still
runs every 30 minutes via the scheduler; the daylight check just
short-circuits the rest of the script on off-hours runs rather than
changing the schedule itself.

## Built-in test mode

A `--test` flag bypasses the daylight check and the state file's seen-URL
tracking, caps output at 3 alerts, and sends a real end-to-end email +
Discord notification — falling back to a placeholder alert if nothing
currently matches, so delivery can be verified without waiting for an
actual sighting. `--test` also bypasses the source-health warning cooldown
(below), so that channel's delivery can be verified the same way.

## Source health monitoring — closes a real gap

A feed can break silently: a site changes its RSS format or a scrape
selector stops matching, and the monitor just quietly stops producing
alerts for that source. Nothing before this would tell you — you'd only
notice by realizing it had been a while since a whale alert came through,
which isn't something you catch quickly for a source that's already
low-frequency by nature. A technical review of this project called out
exactly this: "nothing tells you when a source goes quiet." That gap is
now closed.

Every source in `SOURCES` gets a `last_success` timestamp recorded whenever
`check_rss()`/`check_scrape()` completes its fetch and parse without an
exception — deliberately independent of whether anything matched a
keyword, since most runs legitimately find nothing and that's not a health
problem. If a source's `last_success` is more than 48 hours old, it's
flagged stale; a warning fires through the same email + Discord channels
used for sighting alerts (in amber, distinct from the blue used for actual
sightings), independent of whether there are any whale alerts to send that
run. A 24-hour cooldown on repeat warnings keeps it from re-alerting every
30 minutes once triggered.

One edge case worth naming: health tracking only checks sources currently
listed in `SOURCES`. When Orca Network was disabled, it would otherwise
still be sitting in an old state file and warning as "stale" forever, for
a source that was deliberately turned off, not broken. Checking the active
source list first avoids that.

## Bug found and fixed: silent partial staleness

The source-health monitoring above catches a feed going fully silent — zero
successful fetches for 48+ hours. It does not catch a feed that's
technically alive, returning `200 OK` on every request, while silently
missing individual entries. That's a different failure mode entirely, and
nothing before this caught it.

It surfaced in person: a real sighting post ("WHALES: Orcas in Elliott
Bay," posted 8:26am) never triggered an alert. Investigating turned up the
actual cause — West Seattle Blog's dedicated whale-category feed lags
behind their main site feed. The post was live on the main feed the whole
time; it just never appeared in the category feed the monitor was actually
polling.

The fix was switching polling to the main feed — but that immediately
surfaced a second issue. The main feed is unfiltered, and three of the
existing keywords ("Alki," "Elliott Bay," "West Seattle") are neighborhood
names that show up in nearly every West Seattle Blog post's body text
regardless of subject. Initial dry-run testing against the main feed
produced 11 "matches," 10 of them false positives from those three
keywords alone.

Those three were removed after confirming every genuine historical match
already had a species word — "whale," "orca" — directly in the title, so
dropping the neighborhood terms cost no real coverage. A second, narrower
false positive turned up next: "Whale Tail Park," an actual West Seattle
playground, matches on the word "whale" by itself. Rather than remove
"whale" from the keyword list, that's handled with a small exclusion list
for known false-positive phrases.

Verified before trusting any of this: the dry run went from 11 false
matches down to exactly one real one once the keyword list and exclusion
list were both in place. A live run then correctly caught the originally
missed post and delivered it through both email and Discord, and a
follow-up run confirmed no duplicate alert went out for it.

Residual risk, stated plainly: this trades the old staleness problem for
an ongoing, small chance that some other unrelated post collides with a
keyword the same way Whale Tail Park did. That's not solved permanently —
it's handled case-by-case via the exclusion list as new collisions turn up.

## Known limitations

- The daylight/keyword design assumes shore-based, in-person photography —
  it isn't trying to predict where a whale will be, just to surface reports
  as they're published.
- With Orca Network's public sightings page gone, the source list is down
  to two RSS feeds; if either publication changes its feed format or goes
  offline, that's a real reduction in coverage. The source-health check
  above means that would now surface as a warning within a couple of days
  rather than going unnoticed indefinitely, but it's still a loss of
  coverage, not a fix for it.

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in `TO_EMAIL`, `SMTP_USER`,
   `SMTP_PASS` (a Gmail App Password, not your real password — Google
   Account → Security → 2-Step Verification → App passwords), and
   optionally `DISCORD_WEBHOOK_URL`.
3. Test delivery end-to-end without waiting for a live sighting:
   `python whale_alert.py --test`
4. Schedule it for a 30-minute cadence (Windows Task Scheduler, or
   cron/launchd on macOS/Linux).

---

# Historical Sighting Trends & Migration Map

Everything above is the live alert — it tells you a sighting happened
right now and has no memory beyond that. This extends the same project
with a persistent store and analysis layer so patterns become visible:
which species and pods visit which locations, how timing shifts season to
season, and what activity looks like anywhere in Washington waters, not
just West Seattle.

**Scope:** orca, humpback, and gray whale (broadened from orcas-only —
every species the live monitor already flags). Pod-level ID (J/K/L,
Bigg's/Transient) is orca-specific; humpback and gray whale sightings are
tracked by species only for now (individual humpback fluke-ID tracking is
a stretch goal, not built here — see Known limitations).

## Alerts vs. tracker: two separate geographic scopes

This is the one thing worth understanding before anything else here: the
live alert above and this tracker use the same underlying coordinate data
but are **deliberately separate code paths, not a shared filter**.

- **Live alerts** (`alerts/geo_filter.py`) — a hard boolean gate.
  Push notifications now only fire for sightings within a configurable
  radius of West Seattle (default ~8mi, covering Alki Point/Emma Schmitz
  Overlook/Lincoln Park — tunable via `ALERT_RADIUS_MILES`, not
  hardcoded). Either a sighting is close enough to notify on, or it isn't.
- **Historical tracker** (`analysis/location_query.py`) — an interactive
  query parameter, no geographic restriction. Pulls up activity for any
  named WA region on demand — e.g. San Juan Island while actually
  visiting — without that data ever having triggered a push notification.

Building one shared geographic filter and reusing it for both would have
conflated a decision ("should this notify me") with a browsing parameter
("show me this region"); they're accurate distance calculations for two
different questions.

## New data sources

| Source | What it adds | Status |
|---|---|---|
| [Acartia](https://acartia.io) | Structured Salish Sea sighting data, all species/providers | **Live and verified** — `GET https://acartia.io/api/v1/sightings/current`, no auth, confirmed against a real request |
| Orca Network historical archive | Backfill beyond the live RSS feed above | **Not live** — their relaunched site doesn't have a working archive page yet (same root cause as the live alert's disabled Orca Network scrape source). Built and ready; returns `[]` with a clear log message rather than a fabricated scrape |
| Bonneville Dam adult passage (DART/CBR) | Daily Columbia-system Chinook counts, a real salmon-abundance signal | **Live and verified** — real CSV, no key |
| Albion test fishery Chinook CPUE (DFO/Fraser Panel) | The specific salmon-abundance source named in the original spec | **Not verified** — couldn't confirm a clean real-time structured endpoint in reasonable research time (DFO's open data catalog only has post-season commercial estimates). Built and pointed at the real source, flagged unverified rather than faked |
| NOAA CO-OPS tide predictions | Tide state (flood/ebb/slack) | **Live and verified** — keyless, station 9447130 (Seattle) |
| Moon phase | Experimental/exploratory only | Computed locally via `astral`, no external source, can't go stale |

Two of six sources turned out not to have a working live endpoint I could
verify — documented and built to fail gracefully rather than hidden or
faked, same principle as the disabled Orca Network scrape source in the
live alert above.

## Feature hierarchy: salmon (orca-only) > tide > moon phase

1. **Salmon abundance (Chinook CPUE)** — a strong, evidence-backed
   predictor of **orca** presence specifically at a pod level (multiple
   long-term studies tie SRKW habitat use to Chinook returns). Does
   **not** apply to humpback (krill/small fish) or gray whale (benthic
   amphipods) — `environmental_context.chinook_cpue` is joined to orca
   records only.
2. **Tide state** — a secondary modifier, relevant across all species
   since tide-driven current and prey behavior affects foraging broadly.
3. **Moon phase** — unproven and exploratory, included to test the
   hypothesis honestly rather than because it's relied on. Every value
   lives under `experimental_moon_phase` — schema, code, and here — and
   must never get presented as a validated predictor.

## Species & pod normalization

Free text is messy — sources describe sightings informally ("J & L pods,
Whidbey Island"). `normalization/pod_resolver.py` turns that into
structured categories (`J`/`K`/`L`/`BIGGS_TRANSIENT`/`SRKW_UNSPECIFIED`)
with an explicit `UNKNOWN` bucket for orca records that don't resolve —
never a silent guess. Non-orca species always get `pod_code = None`,
regardless of what the text happens to contain.

**Bug found and fixed:** the first version only matched a pod letter
directly adjacent to the word "pod" (`"J pod"`). Real text routinely
shares one "pod(s)" across a list — the spec's own example, `"J & L pods,
Whidbey Island"`, has "L" nowhere near "pod" at all. My own test caught
this (written for a similar case, `"L and J pods traveling together"`,
before I'd even seen the spec's exact phrasing) — it failed, and I fixed
the regex to detect a shared-suffix list rather than weakening the test.
Verified against real live Acartia comment text, not just synthetic
cases: correctly resolved `"...at least J and K pods per OBI post..."`
(an actual, messy sentence from a real sighting) to `J,K`.

## Storage & source health

SQLite (`storage/schema.sql`), with two additions beyond a literal
species/pod/location table: `external_id` for dedup on re-ingestion
(confirmed via a real re-run: 98 real Acartia sightings ingested, 0 new
on a second pass), and `sighting_time` — tide state depends on the
moment, not just the date.

`storage/source_health` applies the exact same pattern already used for
the live alert (`last_success`, 48-hour staleness threshold), extended
with `consecutive_zero_runs` — a signal specific to historical ingestion,
where a source can "succeed" (no error) while returning nothing new for
weeks, which is exactly the Orca Network archive's current, documented
state above.

## Analysis: pivots, region query, map, trends

- `analysis/pivots.py` — orca sightings by pod × month, sightings by
  species × month, sightings by location × species. A single sighting
  mentioning two pods together (`"J,L"`) is exploded so it correctly
  counts toward both, not just the first.
- `analysis/location_query.py` — the unrestricted region query described
  above (`query_region()`/`query_point()`).
- `viz/map.py` — folium map, color-coded by species, orca markers further
  sub-colored by pod, filterable by date range and location/region
  independently.
- `viz/trends.py` — plotly trend charts over time, built directly on the
  same pivot tables (one source of truth for both).

All four verified end to end against real live Acartia data, not just
fixtures — see each module's commit for the actual numbers.

## Local dashboard

`dashboard/app.py` (Flask) wraps the map, pivot tables, and region query
in a browsable local UI — `/`, `/map`, `/pivots`, `/region/<name>`. Build
and test entirely via `python -m dashboard.app` or `flask run`; no
deployment in this PR (see Phase 2 below).

*Sample screenshot:* I ran the dashboard locally and visually confirmed
all four routes render correctly against real ingested data (species
counts, a real Puget Sound map with color-coded markers, real pivot
tables). I don't have a way to commit a binary screenshot file through
the tools available to me for this session, so there isn't an image
embedded here — `python -m dashboard.app` and opening `127.0.0.1:5000`
reproduces exactly what I saw in under a minute.

**Bug found and fixed:** `python dashboard/app.py` directly fails —
`ModuleNotFoundError: No module named 'analysis'` — because a
directly-executed script only gets its own directory on `sys.path`, not
the repo root, so the sibling `analysis`/`storage`/`viz` packages aren't
importable. Run as `python -m dashboard.app` from the repo root instead
(or `flask run`, which handles this correctly). Documented directly in
`dashboard/app.py`'s `__main__` block, found the same way.

## `/whales` Discord slash command — a different operational model

Reuses Acartia's live `/current` endpoint for a phone-checkable activity
summary. Stated plainly rather than glossed over: this **requires a
continuously-running bot process** (discord.py's gateway/WebSocket
connection), which is a different operational model than the live
alert's fire-and-forget webhook or the dashboard's on-demand local
server. Not solved in this PR — needs either a machine staying on or the
Phase 2 Render deployment below. It's a **separate, additive** bot
application (own `DISCORD_BOT_TOKEN`, `applications.commands` scope,
invited alongside the existing webhook) — never touches
`DISCORD_WEBHOOK_URL`.

The business logic (fetch current sightings, format a reply) has no
Discord dependency and is fully tested against real live data; the
discord.py wiring itself genuinely can't be tested without a real bot
token, so it's kept separate and thin, and confirmed to at least
construct correctly and fail cleanly (not obscurely) without one.

**Bug found and fixed:** the package was originally named `discord/`,
matching the spec's file tree — which **shadows the installed discord.py
library**. `import discord` inside it resolved to itself (empty) instead
of the real library, breaking bot construction entirely with a confusing
`ImportError`. Found by actually trying to construct the client, not by
inspection. Renamed to `discord_bot/`.

## CLI: ingest + regenerate reports

`python -m ingestion.run_backfill` ingests every source, enriches new
sightings with environmental context, logs any stale sources, and
regenerates the map + both trend charts + all three pivot tables.

Honest scope note: despite a `--season` flag (kept for interface
compatibility with the original spec), this currently ingests Acartia's
real-time `/current` window (last 7 days) rather than a deep historical
backfill — true backfill needs Acartia's authenticated historical
endpoints (approval-gated) or a live Orca Network archive (not live yet).
Both are already wired up and will start contributing real depth the
moment either becomes available, with zero code changes needed here.
Running this regularly (the same scheduler as the live alert, or by hand)
is how historical depth actually accumulates in the meantime.

Run for real against the actual project database, not a throwaway test
one: 98 real sightings ingested and enriched with real tide state/height
and moon phase, reports regenerated, pivot tables correct.

## Data sources

Whale sighting data provided by [Acartia](https://acartia.io), a
decentralized data cooperative for the Salish Sea, with founding data
contributions from [Orca Network](https://orcanetwork.org) and
[Orcasound](https://orcasound.net). Salmon abundance data from Bonneville
Dam adult passage counts ([DART](https://www.cbr.washington.edu/dart/),
U. Washington Columbia Basin Research) and, once verified, the Albion
test fishery (DFO/Fraser River Panel). Tide data from
[NOAA CO-OPS](https://tidesandcurrents.noaa.gov/).

`salish-sea/orca-salmon` is a similar existing dashboard (Chinook counts
+ SRKW occurrence) — used only as a reference for what's possible, not as
source material. The Bonneville/tide ingestion here was built
independently against the public data sources directly, not adapted from
their code.

## Known limitations (historical trends)

- Two of six new data sources (Orca Network archive, Albion CPUE) don't
  have a verified live endpoint yet — see New data sources above. Wired
  up and ready, not faked.
- `/whales` needs a persistent bot process, unsolved until Phase 2 or a
  machine stays on continuously.
- Individual humpback fluke-ID tracking (Happywhale-style) is a stretch
  goal — no API exists for it; out of scope for this PR.
- No predictive/forecasting model — this surfaces reports and historical
  patterns, it doesn't predict where a whale will be next.
- Chinook CPUE is presented as a correlate for orca records, not a
  causal claim — the feature hierarchy above exists specifically to keep
  that distinction visible in the schema and code, not just in this
  paragraph.

## Phase 2 (documented, not built in this PR)

Deploy the local dashboard (already built and tested above) to Render's
free tier for real mobile browser access. Deliberately split from the
dashboard build itself: this PR gets the harder, more valuable part (the
actual dashboard) built and proven on `localhost`, with no hosting
decisions needed yet; deployment becomes a low-risk, mechanical step
whenever it's time. Render is the only platform with a genuine permanent
free tier as of 2026 (Railway and Fly.io both dropped theirs) — worth
knowing that the trade-off is a ~60s cold start after 15 minutes of
inactivity before relying on it mid-trip.

## Historical trends setup

1. `pip install -r requirements.txt` (now includes pandas, folium,
   plotly, Flask, discord.py, pytest)
2. `.env` additions (all optional, all in `.env.example`):
   `ACARTIA_API_TOKEN`, `DISCORD_BOT_TOKEN` (separate from
   `DISCORD_WEBHOOK_URL`), `ALERT_CENTER_LAT`/`ALERT_CENTER_LON`/
   `ALERT_RADIUS_MILES`.
3. Ingest and regenerate reports: `python -m ingestion.run_backfill`
4. Run the dashboard: `python -m dashboard.app`, then open
   `http://127.0.0.1:5000`
5. Run the test suite: `pytest tests/`
