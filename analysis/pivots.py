"""
Pivot-table trend analysis over stored sightings.

No geographic restriction here -- see spec §1a. This covers all Washington
waters; the tracker's location-scoped queries live in location_query.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis.correlations import derive_season
from normalization.location_geocoder import nearest_known_location
from normalization.pod_resolver import VALID_SPECIES
from storage.db import query_sightings

# Data-quality metric (2026-09-08): a pod_code of "J"/"K"/"L"/"BIGGS_TRANSIENT"
# means a specific pod or ecotype was actually identified. "SRKW_UNSPECIFIED"
# (a Southern Resident sighting, pod not determined) and "UNKNOWN"/missing are
# both a real gap in identification, not a 5th resolved category -- lumping
# them as "unresolved" is what makes the resulting rate meaningful as a
# data-quality signal rather than just a category count.
_RESOLVED_POD_CODES = {"J", "K", "L", "BIGGS_TRANSIENT"}


def _sightings_dataframe(conn: sqlite3.Connection, **query_kwargs) -> pd.DataFrame:
    rows = query_sightings(conn, **query_kwargs)
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return df
    df["sighting_date"] = pd.to_datetime(df["sighting_date"])
    df["month"] = df["sighting_date"].dt.to_period("M").astype(str)
    return df


def pod_by_month(conn: sqlite3.Connection) -> pd.DataFrame:
    """Orca sightings, pod × month. A single sighting can carry multiple
    comma-joined pod codes (e.g. "J,L") -- each contributes to both rows,
    since it's a real observation of both pods, not a single ambiguous one."""
    df = _sightings_dataframe(conn, species="orca")
    if df.empty:
        return pd.DataFrame()

    df = df.assign(pod_code=df["pod_code"].fillna("UNKNOWN").str.split(",")).explode("pod_code")
    return pd.pivot_table(
        df, index="pod_code", columns="month", values="id", aggfunc="count", fill_value=0
    )


def species_by_month(conn: sqlite3.Connection) -> pd.DataFrame:
    """All species, species × month."""
    df = _sightings_dataframe(conn)
    if df.empty:
        return pd.DataFrame()
    return pd.pivot_table(
        df, index="species", columns="month", values="id", aggfunc="count", fill_value=0
    )


def location_by_species(conn: sqlite3.Connection) -> pd.DataFrame:
    """Sightings by location × species. Rows with no location_name are
    grouped under 'unknown_location' rather than dropped -- Acartia gives
    lat/lon directly but not always a place name."""
    df = _sightings_dataframe(conn)
    if df.empty:
        return pd.DataFrame()
    df = df.assign(location_name=df["location_name"].fillna("unknown_location"))
    return pd.pivot_table(
        df, index="location_name", columns="species", values="id", aggfunc="count", fill_value=0
    )


def recent_24h_summary(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """'X sightings of [species] near [location] in the last 24 hours,'
    broken out by species and location, for the dashboard home page.

    `now` defaults to real UTC now (sighting timestamps are confirmed UTC
    -- see ingestion/acartia_client.py) but is overridable for testing
    against a fixed clock rather than whatever the real time happens to
    be when a test runs.

    Location is reverse-geocoded via nearest_known_location() (Acartia
    gives lat/lon, not a place name) and grouped into "far from any known
    viewpoint" rather than silently dropped or mislabeled when nothing is
    within range.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)

    # Broad SQL prefilter on date alone (cheap, sargable), exact 24h cutoff
    # applied in Python below since sighting_time can be NULL and mixing
    # NULL-safe time comparison into SQL here isn't worth the complexity
    # for a table this size.
    rows = conn.execute(
        "SELECT species, pod_code, latitude, longitude, sighting_date, sighting_time "
        "FROM sightings WHERE sighting_date >= :cutoff_date",
        {"cutoff_date": window_start.date().isoformat()},
    ).fetchall()

    in_window = []
    for row in rows:
        time_part = row["sighting_time"] or "00:00:00"
        sighting_dt = datetime.fromisoformat(f"{row['sighting_date']}T{time_part}").replace(tzinfo=timezone.utc)
        if window_start <= sighting_dt <= now:
            in_window.append(row)

    if not in_window:
        return {"total": 0, "groups": [], "window_start": window_start, "window_end": now}

    groups: dict[tuple[str, str], int] = {}
    for row in in_window:
        location = nearest_known_location(row["latitude"], row["longitude"]) if row["latitude"] else None
        key = (row["species"], location or "an unmapped location")
        groups[key] = groups.get(key, 0) + 1

    sorted_groups = [
        {"species": species, "location": location, "count": count}
        for (species, location), count in sorted(groups.items(), key=lambda kv: -kv[1])
    ]

    return {
        "total": len(in_window),
        "groups": sorted_groups,
        "window_start": window_start,
        "window_end": now,
    }


def season_total_with_change(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """KPI (2026-09-08): total sightings in the current meteorological
    season (see analysis/correlations.py's derive_season -- same
    definition, so this and the seasonal chart never disagree about what
    "this season" means), plus week-over-week momentum: the last 7 days
    vs. the 7 days before that.

    Week-over-week rather than month-over-month -- more sensitive for a
    dashboard meant to be checked regularly, and it doesn't need a full
    month of data to say anything, which month-over-month would on a
    project this new. `change_pct` is None (not 0 or inf) when the prior
    week had zero sightings -- a percentage change from zero is undefined,
    not "infinite growth" or "no change."
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    season = derive_season(today)
    season_months = {
        "winter": {12, 1, 2}, "spring": {3, 4, 5}, "summer": {6, 7, 8}, "fall": {9, 10, 11},
    }[season]

    rows = conn.execute("SELECT sighting_date FROM sightings").fetchall()
    dates = [datetime.strptime(r["sighting_date"], "%Y-%m-%d").date() for r in rows]

    # Winter spans a year boundary (Dec-Feb); every other season is
    # entirely within one calendar year, so "this season" only needs a
    # year match for those three.
    if season == "winter":
        season_year = today.year if today.month == 12 else today.year - 1
        season_total = sum(
            1 for d in dates
            if d.month in season_months and (d.year == season_year + 1 if d.month != 12 else d.year == season_year)
        )
    else:
        season_total = sum(1 for d in dates if d.month in season_months and d.year == today.year)

    week_start = today - timedelta(days=7)
    prior_week_start = today - timedelta(days=14)
    current_week = sum(1 for d in dates if week_start <= d <= today)
    prior_week = sum(1 for d in dates if prior_week_start <= d < week_start)

    change_pct = None if prior_week == 0 else round((current_week - prior_week) / prior_week * 100, 1)

    return {
        "season": season,
        "season_total": season_total,
        "current_week_count": current_week,
        "prior_week_count": prior_week,
        "change_pct": change_pct,
    }


def most_active_location(conn: sqlite3.Connection, now: datetime | None = None, window_hours: int = 24) -> dict:
    """KPI: the single named location with the most sightings in the last
    `window_hours` -- "right now" per the ask, so 24h by default, same
    window as the home page's recent_24h_summary (deliberately reusing
    that window rather than inventing a second one for consistency
    between the two home-page KPIs). Ties broken by whichever location
    sorts first alphabetically -- arbitrary but deterministic, not
    meaningful on its own.

    Returns location=None (not a location picked at random) when nothing
    is in the window, or when every sighting in the window falls outside
    known-location range -- both are real "no answer" cases, not bugs."""
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    rows = conn.execute(
        "SELECT latitude, longitude, sighting_date, sighting_time FROM sightings "
        "WHERE sighting_date >= :cutoff_date",
        {"cutoff_date": window_start.date().isoformat()},
    ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        time_part = row["sighting_time"] or "00:00:00"
        sighting_dt = datetime.fromisoformat(f"{row['sighting_date']}T{time_part}").replace(tzinfo=timezone.utc)
        if not (window_start <= sighting_dt <= now):
            continue
        if row["latitude"] is None:
            continue
        location = nearest_known_location(row["latitude"], row["longitude"])
        if location is None:
            continue
        counts[location] = counts.get(location, 0) + 1

    if not counts:
        return {"location": None, "count": 0, "window_hours": window_hours}

    top_location = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"location": top_location[0], "count": top_location[1], "window_hours": window_hours}


def days_since_last_sighting(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int | None]:
    """KPI: for every valid species, how many whole days since its most
    recent sighting -- a "gone quiet" indicator per species. A species
    with zero sightings ever gets None, not a misleadingly large number
    (there's no "last sighting" to count days since)."""
    now = now or datetime.now(timezone.utc)
    result: dict[str, int | None] = {species: None for species in VALID_SPECIES}

    rows = conn.execute(
        "SELECT species, MAX(sighting_date) AS last_date FROM sightings GROUP BY species"
    ).fetchall()
    for row in rows:
        if row["species"] not in result or row["last_date"] is None:
            continue
        last_date = datetime.strptime(row["last_date"], "%Y-%m-%d").date()
        result[row["species"]] = (now.date() - last_date).days

    return result


def orca_pod_resolution_rate(conn: sqlite3.Connection) -> dict:
    """Data-quality KPI: of all orca sightings, what fraction actually got
    a specific pod identified (J/K/L/Bigg's) vs. left as
    SRKW-unspecified-or-unknown. Low resolution doesn't mean the
    sightings are wrong -- it means the source reports didn't include
    enough detail to identify a pod, which is itself useful to know
    about the data, hence surfacing it as a KPI rather than only inside
    the pod x month pivot table."""
    rows = conn.execute("SELECT pod_code FROM sightings WHERE species = 'orca'").fetchall()
    total = len(rows)
    if total == 0:
        return {"resolved": 0, "unresolved": 0, "total": 0, "resolution_rate_pct": None}

    resolved = sum(
        1 for row in rows
        if row["pod_code"] and any(p in _RESOLVED_POD_CODES for p in row["pod_code"].split(","))
    )
    unresolved = total - resolved
    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "total": total,
        "resolution_rate_pct": round(resolved / total * 100, 1),
    }


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    print("=== Orca sightings: pod x month ===")
    print(pod_by_month(conn))
    print("\n=== Sightings: species x month ===")
    print(species_by_month(conn))
    print("\n=== Sightings: location x species ===")
    print(location_by_species(conn))
