"""
Albion test fishery Chinook CPUE ingestion (DFO / Pacific Salmon Commission).

Salmon abundance -- specifically Fraser River Chinook returns -- is a real,
published predictor of SRKW (Southern Resident orca) presence at the pod
level (see README "Feature hierarchy"). This joins to orca sightings only;
never to humpback or gray whale records, whose diets aren't salmon-based.

**Status, researched 2026-08-27 (not assumed):** unlike Acartia and NOAA
CO-OPS (both confirmed against live requests -- see acartia_client.py and
tide.py), I could not confirm a clean, structured, real-time public API for
daily Albion CPUE within reasonable research time:
  - DFO's open data catalog (open.canada.ca) has Pacific salmon datasets,
    but they're post-season commercial catch estimates (Fishery Operations
    System / FOS), not a daily in-season Albion test-fishery feed.
  - The authoritative real-time source is the Pacific Salmon Commission's
    Fraser Panel in-season updates (pacificsalmoncommission.org), which
    historically publish as bulletins during the summer season rather than
    a stable JSON/CSV endpoint.

Rather than fabricate a parser against a page format I haven't verified
(same principle as orca_network_archive.py), this module is structured
correctly and points at the real source, but CPUE_SOURCE_VERIFIED is False
until someone confirms the actual current bulletin URL/format during an
active season and updates the parser accordingly. fetch_chinook_cpue()
returns an empty list and logs why, rather than raising or guessing.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20

# Real organization, real program -- URL format not yet confirmed against
# a live in-season bulletin. See module docstring.
FRASER_PANEL_URL = "https://www.pacificsalmoncommission.org/test-fishing/"
CPUE_SOURCE_VERIFIED = False


class ChinookCpueError(Exception):
    pass


@dataclass
class ChinookCpueRecord:
    record_date: date
    cpue: float
    source_note: str


def fetch_chinook_cpue(start: date, end: date) -> list[ChinookCpueRecord]:
    """Fetch Albion test fishery Chinook CPUE for a date range.

    Returns [] and logs a clear reason while CPUE_SOURCE_VERIFIED is False,
    matching the documented, honest "not confirmed live" state -- same
    pattern as ingestion/orca_network_archive.py. Once someone confirms the
    real in-season bulletin URL/format (only available during the Fraser
    Panel's active season), flip CPUE_SOURCE_VERIFIED and implement the
    actual fetch/parse here.
    """
    if not CPUE_SOURCE_VERIFIED:
        logger.info(
            "Chinook CPUE source not yet verified live (see module docstring) -- "
            "returning no records rather than fabricating a parse. "
            "Check %s during an active Fraser Panel season to confirm the real format.",
            FRASER_PANEL_URL,
        )
        return []

    raise NotImplementedError("Implement once CPUE_SOURCE_VERIFIED is confirmed True.")


# ── Bonneville Dam adult passage counts ─────────────────────────────────
# Unlike Albion CPUE above, this one IS confirmed against a live request
# (2026-08-27): DART (Data Access in Real Time, U. Washington Columbia
# Basin Research) publishes daily adult fish counts as plain CSV, no key
# required. Columbia River system, not Fraser -- a different, complementary
# salmon-abundance signal, same evidentiary basis (orca-only join).

DART_URL = "https://www.cbr.washington.edu/dart/cs/php/rpt/adult_daily.php"


@dataclass
class BonnevillePassageRecord:
    record_date: date
    chinook_count: int
    jack_chinook_count: int


def fetch_bonneville_passage(start: date, end: date, year: int | None = None) -> list[BonnevillePassageRecord]:
    """Fetch daily adult Chinook passage counts at Bonneville Dam.

    Confirmed live: returns real CSV columns including 'Chin' (adult
    Chinook) and 'JChin' (jack Chinook) per day.
    """
    year = year or start.year
    params = {
        "sc": "1",
        "outputFormat": "csv",
        "year": str(year),
        "proj": "BON",
        "startdate": f"{start.month}/{start.day}",
        "enddate": f"{end.month}/{end.day}",
        "run": "",
    }
    try:
        resp = requests.get(DART_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ChinookCpueError(f"request to DART ({DART_URL}) failed: {exc}") from exc

    records: list[BonnevillePassageRecord] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        # DART's CSV response trails off into blank/malformed rows past the
        # real data (confirmed live: rows 8+ come back as all-None) --
        # skip those rather than let a bad row sink the whole fetch.
        if not row.get("Date"):
            continue
        try:
            record_date = date.fromisoformat(row["Date"])
            chinook = int(row["Chin"]) if row.get("Chin") not in (None, "") else 0
            jack = int(row["JChin"]) if row.get("JChin") not in (None, "") else 0
        except (KeyError, ValueError) as exc:
            logger.warning("skipped unparseable DART row %r: %s", row, exc)
            continue
        records.append(BonnevillePassageRecord(record_date, chinook, jack))

    return records


if __name__ == "__main__":
    from datetime import timedelta

    logging.basicConfig(level=logging.INFO)
    today = date.today()
    start, end = today - timedelta(days=7), today

    results = fetch_chinook_cpue(start, end)
    print(f"Albion CPUE: fetched {len(results)} record(s).")

    bonneville = fetch_bonneville_passage(start, end)
    print(f"Bonneville passage: fetched {len(bonneville)} record(s).")
    for r in bonneville[:5]:
        print(f"  {r.record_date}  Chinook={r.chinook_count}  Jack={r.jack_chinook_count}")
