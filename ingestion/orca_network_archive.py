"""
Orca Network historical archive parser
=======================================
Extends the same scrape approach already used (and later disabled) in
whale_alert.py's live "Orca Network sightings" source: fetch a page,
parse it with BeautifulSoup, extract sighting records.

**Status, confirmed 2026-08-27 (live check, not assumed):** Orca Network
relaunched their site and it does not currently have a working archive or
recent-sightings page. The site's own "Whale Sighting Network" page lists
"Archives" and "[Recent Sightings Reports]" under Resources, but both
render as plain text, not links -- matching the site's own banner:
"Welcome to our new site! A few features are still coming online."
Checked half a dozen guessable URL patterns
(/recent-sightings, /sighting-archives, /our-programs/whale-sighting-network/archives,
etc.) -- all 404.

This is the same root cause already documented for the disabled live-scrape
source in whale_alert.py's SOURCES list -- not a new problem, the same one,
now affecting the historical archive too.

Rather than fabricate a scraper against a page that doesn't exist, this
module is built correctly and ready to work the moment Orca Network
publishes an archive page: point ARCHIVE_URL at it and update SELECTORS if
needed. Until then, fetch_archive() returns an empty list and logs a clear
reason rather than raising -- matching the "handle gracefully, don't
crash the batch" pattern used everywhere else in this project. Source-health
monitoring (see storage/db.py) will correctly flag this as perpetually
"no recorded successful fetch yet" until it's pointed at a real page --
that's accurate, not a bug.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Not live yet -- see module docstring. Update once Orca Network publishes
# an archive page; the parser below is a reasonable starting guess at
# markup shape (matches the pattern their old site used) but WILL need
# verification against whatever the real page actually looks like.
ARCHIVE_URL = "https://orcanetwork.org/our-programs/whale-sighting-network/"
ARCHIVE_LIVE = False  # flip to True once ARCHIVE_URL actually serves sighting records

REQUEST_TIMEOUT = 20
HEADERS = {"User-Agent": "WhaleSightingTracker/1.0 (historical trend analysis, personal project)"}


class OrcaNetworkArchiveError(Exception):
    """Raised on an actual fetch/parse failure (not the 'not live yet' case, which returns [] instead)."""


@dataclass
class ArchiveRecord:
    raw_text: str
    location_name: str | None
    sighting_date: date | None
    source_url: str


def fetch_archive(url: str = ARCHIVE_URL) -> list[ArchiveRecord]:
    """Fetch and parse Orca Network's historical archive, if it exists.

    Returns an empty list (not an error) while ARCHIVE_LIVE is False, since
    that's a known, documented state rather than a failure. Once flipped to
    True, a genuine fetch/parse failure raises OrcaNetworkArchiveError so
    the source-health layer can record it correctly.
    """
    if not ARCHIVE_LIVE:
        logger.info(
            "Orca Network archive not live yet (see module docstring) -- "
            "returning no records rather than fabricating a scrape."
        )
        return []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OrcaNetworkArchiveError(f"request to {url} failed: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    records: list[ArchiveRecord] = []

    # Best-guess selector, matching the markup pattern their pre-relaunch
    # site used for sighting entries. VERIFY against the real page once
    # ARCHIVE_LIVE is flipped on -- this is a starting point, not a
    # confirmed-working selector (unlike acartia_client.py, which is
    # verified against real live data).
    for entry in soup.select(".sighting-entry, article.sighting, .entry-content li"):
        text = entry.get_text(strip=True)
        if not text:
            continue
        link = entry.find("a")
        href = urljoin(url, link["href"]) if link and link.get("href") else url
        records.append(
            ArchiveRecord(raw_text=text, location_name=None, sighting_date=None, source_url=href)
        )

    return records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = fetch_archive()
    print(f"Fetched {len(results)} archive record(s).")
