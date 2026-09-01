"""
Pivot-table trend analysis over stored sightings.

No geographic restriction here -- see spec §1a. This covers all Washington
waters; the tracker's location-scoped queries live in location_query.py.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

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


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    print("=== Orca sightings: pod x month ===")
    print(pod_by_month(conn))
    print("\n=== Sightings: species x month ===")
    print(species_by_month(conn))
    print("\n=== Sightings: location x species ===")
    print(location_by_species(conn))
