"""
Pivot-table trend analysis over stored sightings.

No geographic restriction here -- see spec §1a. This covers all Washington
waters; the tracker's location-scoped queries live in location_query.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd

from normalization.location_geocoder import nearest_known_location
from storage.db import query_sightings


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


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    print("=== Orca sightings: pod x month ===")
    print(pod_by_month(conn))
    print("\n=== Sightings: species x month ===")
    print(species_by_month(conn))
    print("\n=== Sightings: location x species ===")
    print(location_by_species(conn))
