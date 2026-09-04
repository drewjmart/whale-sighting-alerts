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
from folium import MacroElement
from jinja2 import Template

from analysis.location_query import query_point, query_region
from storage.db import query_sightings
from viz.colors import INK_PRIMARY, INK_SECONDARY, POD_COLORS, SPECIES_COLORS, color_for_species_or_pod

DEFAULT_CENTER = (47.7, -122.6)  # roughly central Puget Sound / Salish Sea
DEFAULT_ZOOM = 9

# Legend rows, in a fixed, meaningful order -- most-tracked orca pods first
# (the categories this project's users actually care most about), then
# non-orca species. Matches viz/colors.py exactly; this list IS the legend.
_LEGEND_POD_ROWS = [
    ("J", "Orca -- J pod"),
    ("K", "Orca -- K pod"),
    ("L", "Orca -- L pod"),
    ("BIGGS_TRANSIENT", "Orca -- Bigg's/Transient"),
    ("SRKW_UNSPECIFIED", "Orca -- Southern Resident, pod unconfirmed"),
    ("UNKNOWN", "Orca -- pod unresolved"),
]
_LEGEND_SPECIES_ROWS = [
    ("humpback", "Humpback"),
    ("gray_whale", "Gray whale"),
    ("porpoise", "Porpoise"),
    ("unknown", "Unidentified species"),
]


class _MapLegend(MacroElement):
    """A fixed-position HTML legend overlay -- without this, the map's
    colors are unguessable (that was the actual complaint: 'no way to
    interpret the map without guessing'). Colors pulled from viz/colors.py
    so this can never drift from what the markers themselves use."""

    _template = Template(
        """
        {% macro html(this, kwargs) %}
        <div style="
            position: fixed; bottom: 20px; left: 20px; z-index: 9999;
            background: #fcfcfbee; border: 1px solid #e1e0d9; border-radius: 8px;
            padding: 12px 14px; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
            font-size: 12px; color: {{ this.ink_primary }}; box-shadow: 0 2px 8px rgba(11,11,11,0.12);
            max-width: 210px; line-height: 1.5;">
          <div style="font-weight: 600; margin-bottom: 6px;">Orca, by pod</div>
          {% for code, label in this.pod_rows %}
          <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
            <span style="display:inline-block; width:10px; height:10px; border-radius:50%;
                         background:{{ this.pod_colors[code] }}; flex-shrink:0;"></span>
            <span style="color:{{ this.ink_secondary }};">{{ label }}</span>
          </div>
          {% endfor %}
          <div style="font-weight: 600; margin: 8px 0 6px;">Species</div>
          {% for code, label in this.species_rows %}
          <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
            <span style="display:inline-block; width:10px; height:10px; border-radius:50%;
                         background:{{ this.species_colors[code] }}; flex-shrink:0;"></span>
            <span style="color:{{ this.ink_secondary }};">{{ label }}</span>
          </div>
          {% endfor %}
        </div>
        {% endmacro %}
        """
    )

    def __init__(self):
        super().__init__()
        self.pod_rows = _LEGEND_POD_ROWS
        self.species_rows = _LEGEND_SPECIES_ROWS
        self.pod_colors = POD_COLORS
        self.species_colors = SPECIES_COLORS
        self.ink_primary = INK_PRIMARY
        self.ink_secondary = INK_SECONDARY


def _marker_color(row: sqlite3.Row) -> str:
    return color_for_species_or_pod(row["species"], row["pod_code"])


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

    fmap.get_root().add_child(_MapLegend())

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
