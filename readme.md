# Whale Sighting Alert Automation

A Python monitor that watches for whale sighting reports near West Seattle
and sends a digest the moment something new shows up, so there's no need
to manually check multiple sources throughout the day. Built entirely
self-directed after noticing a manual, repetitive task worth automating.

**Stack:** Python, feedparser, requests, BeautifulSoup4, smtplib (SSL),
astral (sunrise/sunset), Discord webhooks. Runs every 30 minutes via
Windows Task Scheduler.

## Sources

The monitor currently aggregates from two RSS feeds:

- **West Seattle Blog** — dedicated whale category feed.
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

Keyword match (whale, orca, humpback, pod names, location terms like
Alki/Elliott Bay) against title and body text, then a JSON state file
tracking seen URLs, trimmed to the last 2,000 entries so it doesn't grow
unbounded.

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