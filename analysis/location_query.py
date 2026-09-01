"""
On-demand region lookup -- "what's active near San Juan Island right now."

Deliberately separate from alerts/geo_filter.py (see spec §1a): that's a
hard boolean gate for push notifications, scoped to West Seattle only.
This is an interactive query parameter with NO geographic restriction --
any named region or arbitrary point in WA waters, used for browsing while
traveling, not for deciding whether to notify.
"""

from __future__ import annotations

import math
import sqlite3

from normalization.location_geocoder import _LOCATIONS  # reuse the same known-place table
from storage.db import query_sightings

MILES_PER_DEGREE_LAT = 69.0


def _bbox_for_point(lat: float, lon: float, radius_miles: float) -> tuple[float, float, float, float]:
    """Approximate (min_lat, min_lon, max_lat, max_lon) bounding box around
    a point. Approximation, not geodesic-exact -- fine for a region browse
    filter at this scale (a few tens of miles), not for navigation."""
    lat_delta = radius_miles / MILES_PER_DEGREE_LAT
    lon_delta = radius_miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat)) or 1)
    return (lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta)


def known_regions() -> list[str]:
    """Named regions available for query_region() -- same table used by
    normalization/location_geocoder.py for text matching, exposed here so
    a dashboard/CLI can list valid options."""
    return sorted(_LOCATIONS.keys())


def query_region(
    conn: sqlite3.Connection,
    region: str,
    radius_miles: float = 10.0,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: str | None = None,
) -> list[sqlite3.Row]:
    """Sightings within `radius_miles` of a named region (case-insensitive,
    must match normalization/location_geocoder.py's known-place table).
    Raises ValueError for an unrecognized region -- an empty result set
    would be ambiguous with "known region, nothing sighted there"."""
    key = region.strip().lower()
    if key not in _LOCATIONS:
        raise ValueError(
            f"Unrecognized region {region!r}. Known regions: {', '.join(known_regions())}"
        )
    lat, lon = _LOCATIONS[key]
    bbox = _bbox_for_point(lat, lon, radius_miles)
    return query_sightings(conn, start_date=start_date, end_date=end_date, species=species, bbox=bbox)


def query_point(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_miles: float = 10.0,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: str | None = None,
) -> list[sqlite3.Row]:
    """Same as query_region() but for an arbitrary point, not a named place."""
    bbox = _bbox_for_point(lat, lon, radius_miles)
    return query_sightings(conn, start_date=start_date, end_date=end_date, species=species, bbox=bbox)


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    print("Known regions:", ", ".join(known_regions()))
    results = query_region(conn, "san juan island", radius_miles=15)
    print(f"\n{len(results)} sighting(s) within 15mi of San Juan Island:")
    for row in results[:10]:
        print(f"  {row['sighting_date']}  {row['species']:12s}  {row['location_name'] or ''}")
