"""
Folium map of sighting locations, color-coded by species (orca sightings
further distinguishable by pod), filterable by BOTH date range and
location/region -- the two filter dimensions are independent (spec §1a):
date range narrows time, region narrows space, and region uses the same
unrestricted location_query.py as the rest of the tracker (no West
Seattle-only restriction here -- that's the live-alert gate's job, not
this map's).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import folium

from analysis.location_query import query_point, query_region
from storage.db import query_sightings

SPECIES_COLORS = {
    "orca": "red",  # overridden per-pod below when species == orca
    "humpback": "teal",
    "gray_whale": "gray",
    "porpoise": "pink",
    "dolphin": "lightblue",
    "unknown": "black",
}

POD_COLORS = {
    "J": "blue",
    "K": "green",
    "L": "purple",
    "BIGGS_TRANSIENT": "orange",
    "SRKW_UNSPECIFIED": "darkred",
    "UNKNOWN": "lightgray",
}

DEFAULT_CENTER = (47.7, -122.6)  # roughly central Puget Sound / Salish Sea
DEFAULT_ZOOM = 9


def _marker_color(row: sqlite3.Row) -> str:
    if row["species"] == "orca" and row["pod_code"]:
        # Multi-pod records ("J,L") get colored by the first pod in the
        # stable order -- a marker can only have one color; the popup text
        # still shows the full pod_code string.
        first_pod = row["pod_code"].split(",")[0]
        return POD_COLORS.get(first_pod, POD_COLORS["UNKNOWN"])
    return SPECIES_COLORS.get(row["species"], SPECIES_COLORS["unknown"])


def _popup_html(row: sqlite3.Row) -> str:
    pod = f" ({row['pod_code']})" if row["pod_code"] else ""
    trusted = "trusted" if row["trusted"] else ("untrusted" if row["trusted"] is not None else "trust unknown")
    return (
        f"<b>{row['species']}{pod}</b><br>"
        f"{row['sighting_date']} {row['sighting_time'] or ''}<br>"
        f"{row['location_name'] or ''}<br>"
        f"<i>{trusted}, source: {row['source']}</i>"
    )


def build_map(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_miles: float = 15.0,
    species: str | None = None,
) -> folium.Map:
    """Build a folium map of matching sightings. Pass `region` (a known
    place name) OR `lat`/`lon` (an arbitrary point) to also filter by
    location; omit both for all of WA waters within the date range."""
    if region:
        rows = query_region(
            conn, region, radius_miles, start_date=start_date, end_date=end_date, species=species
        )
    elif lat is not None and lon is not None:
        rows = query_point(
            conn, lat, lon, radius_miles, start_date=start_date, end_date=end_date, species=species
        )
    else:
        rows = query_sightings(conn, start_date=start_date, end_date=end_date, species=species)

    center = DEFAULT_CENTER
    zoom = DEFAULT_ZOOM
    if region or (lat is not None and lon is not None):
        if rows:
            center = (rows[0]["latitude"], rows[0]["longitude"])
        zoom = 11

    fmap = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    for row in rows:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        folium.CircleMarker(
            location=(row["latitude"], row["longitude"]),
            radius=6,
            color=_marker_color(row),
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(_popup_html(row), max_width=250),
        ).add_to(fmap)

    return fmap


def save_map(fmap: folium.Map, out_path: Path | str = "map.html") -> Path:
    out_path = Path(out_path)
    fmap.save(str(out_path))
    return out_path


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    fmap = build_map(conn)
    out = save_map(fmap)
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
