"""
Correlation analysis: does sighting frequency actually vary with tide
state, season, or (for orca) salmon abundance -- not just raw data display.

Kept separate from analysis/pivots.py (which answers "how many, grouped
by X") and entirely separate from viz/map.py (which stays purely
spatial/species-focused, per the original spec's §1a design principle
applied here too: don't conflate two different jobs in one module).

Every function here is explicit about sample size and about how much of
the dataset spans multiple years -- a single season of data cannot show
a genuine year-over-year migration pattern, and presenting it as if it
could would be a fabricated conclusion, not an honest one.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd

from ingestion.tide import fetch_tide_predictions, tide_state_exposure_minutes
from storage.db import query_sightings_with_context

# A season-over-season comparison needs sightings from the same season in
# at least two different years to mean anything. Below this, any "pattern"
# shown is just one season's shape, not a repeat.
MIN_YEARS_FOR_SEASONAL_COMPARISON = 2

# Below this many sightings in a tide-state bucket, a count difference is
# more likely sampling noise than a real behavioral signal.
MIN_SAMPLE_SIZE_FOR_TIDE_CLAIM = 30


def derive_season(d: date) -> str:
    """Meteorological season (not astronomical) -- Dec/Jan/Feb = winter,
    etc. Meteorological seasons align to calendar months, which is what
    actually matters for grouping "same months across years" -- the
    astronomical solstice/equinox dates wobble by a few days year to year
    and would misgroup boundary sightings."""
    month = d.month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"  # 9, 10, 11


def data_span_summary(conn: sqlite3.Connection) -> dict:
    """How much real calendar time the dataset actually covers -- drives
    the dynamic 'preliminary data' disclaimers rather than a hardcoded one.
    Recomputed from the live database every call, so it updates on its own
    as more seasons of data accumulate; nothing here needs to change by hand."""
    row = conn.execute("SELECT MIN(sighting_date) AS min_d, MAX(sighting_date) AS max_d FROM sightings").fetchone()
    if not row or not row["min_d"]:
        return {"min_date": None, "max_date": None, "n_years": 0, "is_single_season": True}

    min_d = date.fromisoformat(row["min_d"])
    max_d = date.fromisoformat(row["max_d"])
    years = conn.execute("SELECT DISTINCT strftime('%Y', sighting_date) FROM sightings").fetchall()
    n_years = len(years)

    return {
        "min_date": min_d,
        "max_date": max_d,
        "n_years": n_years,
        "is_single_season": n_years < MIN_YEARS_FOR_SEASONAL_COMPARISON,
    }


def sightings_by_tide_state(conn: sqlite3.Connection) -> dict:
    """Does sighting frequency vary by tide state? Returns raw counts AND
    a rate (sightings per hour of exposure to that state), plus an honest
    read on whether the sample supports saying anything.

    Raw counts alone would be misleading here and were caught by looking
    at the actual numbers, not just running the query: 'slack' is a fixed
    +/-30min band around every tide extreme, while 'flood'/'ebb' are the
    multi-hour legs between extremes -- so slack's time window is
    mechanically ~5-6x smaller. On the real data this produced 685 slack
    sightings vs. 1,617-1,881 for flood/ebb, which reads as "way fewer
    whales at slack tide" until you account for slack getting a fraction
    of the observation time to begin with. The rate below corrects for
    that; the raw counts are kept alongside for transparency.
    """
    rows = query_sightings_with_context(conn, require_tide=True)
    df = pd.DataFrame([dict(r) for r in rows])

    if df.empty:
        return {"counts": {}, "rates_per_hour": {}, "total": 0, "sufficient_sample": False,
                "note": "No tide-tagged sightings yet."}

    counts = df["tide_state"].value_counts().to_dict()
    total = len(df)

    min_date = pd.to_datetime(df["sighting_date"]).min().date()
    max_date = pd.to_datetime(df["sighting_date"]).max().date()
    try:
        events = fetch_tide_predictions(
            datetime.combine(min_date, datetime.min.time()) - timedelta(days=1),
            datetime.combine(max_date, datetime.min.time()) + timedelta(days=1),
        )
        exposure_minutes = tide_state_exposure_minutes(events)
        rates_per_hour = {
            state: round(count / (exposure_minutes.get(state, 0) / 60), 3) if exposure_minutes.get(state) else None
            for state, count in counts.items()
        }
    except Exception:
        rates_per_hour = {state: None for state in counts}

    smallest_bucket = min(counts.values()) if counts else 0
    sufficient = smallest_bucket >= MIN_SAMPLE_SIZE_FOR_TIDE_CLAIM and len(counts) >= 2

    if not sufficient:
        note = (
            f"Smallest tide-state bucket has only {smallest_bucket} sighting(s) "
            f"(want >= {MIN_SAMPLE_SIZE_FOR_TIDE_CLAIM}) -- not enough to say tide state "
            f"actually affects sighting frequency yet, as opposed to random variation."
        )
    else:
        note = (
            "Rate (per hour of exposure) is the fair comparison -- raw counts favor "
            "flood/ebb simply because those windows are hours long vs. slack's ~30min "
            "band. Even the rate is observational, not causal: more observers out at "
            "certain tide times would also produce a pattern like this."
        )

    return {
        "counts": counts,
        "rates_per_hour": rates_per_hour,
        "total": total,
        "sufficient_sample": sufficient,
        "note": note,
    }


def sightings_by_season_and_year(conn: sqlite3.Connection) -> tuple[pd.DataFrame, dict]:
    """Cross-year seasonal view: does sighting timing repeat year to year?
    Returns (pivot table, span metadata) -- callers use the span metadata
    to decide whether to show a 'preliminary, single season' notice."""
    rows = conn.execute("SELECT sighting_date, species FROM sightings").fetchall()
    span = data_span_summary(conn)

    if not rows:
        return pd.DataFrame(), span

    df = pd.DataFrame([dict(r) for r in rows])
    df["sighting_date"] = pd.to_datetime(df["sighting_date"])
    df["year"] = df["sighting_date"].dt.year
    df["season"] = df["sighting_date"].dt.date.map(derive_season)

    season_order = ["winter", "spring", "summer", "fall"]
    pivot = pd.pivot_table(df, index="season", columns="year", values="sighting_date", aggfunc="count", fill_value=0)
    pivot = pivot.reindex(season_order)  # fixed, meaningful order rather than however pandas sorts

    return pivot, span


def chinook_cpue_trend(conn: sqlite3.Connection) -> pd.DataFrame:
    """Daily Chinook CPUE (Bonneville passage count, used as the CPUE
    proxy) over the season -- orca-relevant only, per the feature
    hierarchy. One row per date with data, not one row per sighting."""
    rows = query_sightings_with_context(conn, species="orca", require_chinook=True)
    if not rows:
        return pd.DataFrame(columns=["date", "chinook_cpue"])

    df = pd.DataFrame([dict(r) for r in rows])
    daily = df.groupby("sighting_date", as_index=False)["chinook_cpue"].first()
    daily = daily.rename(columns={"sighting_date": "date"}).sort_values("date")
    return daily


def tide_height_trend(conn: sqlite3.Connection) -> pd.DataFrame:
    """Tide height over the same date range as the data, for placing next
    to the sightings-by-tide-state chart. Uses the tide_height_ft already
    stored per sighting (averaged per day) rather than a fresh NOAA call --
    keeps this function fast and dependency-free for the dashboard route;
    ingestion/tide.py's live predictions are what populated these values
    in the first place."""
    rows = query_sightings_with_context(conn, require_tide=True)
    if not rows:
        return pd.DataFrame(columns=["date", "tide_height_ft"])

    df = pd.DataFrame([dict(r) for r in rows])
    daily = df.groupby("sighting_date", as_index=False)["tide_height_ft"].mean()
    daily = daily.rename(columns={"sighting_date": "date"}).sort_values("date")
    return daily
