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
from folium.plugins import MarkerCluster
from jinja2 import Template

from analysis.location_query import query_point, query_region
from storage.db import query_sightings
from viz.colors import chart_chrome, color_for_species_or_pod, pod_colors, species_colors

DEFAULT_CENTER = (47.7, -122.6)  # roughly central Puget Sound / Salish Sea
DEFAULT_ZOOM = 9

# Rows in a fixed, meaningful order -- most-tracked orca pods first (the
# categories this project's users actually care most about), then non-orca
# species. Matches viz/colors.py exactly; this list IS the legend, and is
# also reused (2026-09-08) by dashboard/app.py to build the /map pod and
# species filter checkboxes, so the legend and the filters can never list
# different categories from each other.
POD_ROWS = [
    ("J", "Orca -- J pod"),
    ("K", "Orca -- K pod"),
    ("L", "Orca -- L pod"),
    ("BIGGS_TRANSIENT", "Orca -- Bigg's/Transient"),
    ("SRKW_UNSPECIFIED", "Orca -- Southern Resident, pod unconfirmed"),
    ("UNKNOWN", "Orca -- pod unresolved"),
]
SPECIES_ROWS = [
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
            background: {{ this.surface }}; border: 1px solid {{ this.gridline }}; border-radius: 8px;
            padding: 12px 14px; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
            font-size: 12px; color: {{ this.ink_primary }}; box-shadow: {{ this.shadow }};
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

    def __init__(self, theme: str = "light"):
        super().__init__()
        chrome = chart_chrome(theme)
        self.pod_rows = POD_ROWS
        self.species_rows = SPECIES_ROWS
        self.pod_colors = pod_colors(theme)
        self.species_colors = species_colors(theme)
        self.ink_primary = chrome["ink_primary"]
        self.ink_secondary = chrome["ink_secondary"]
        # Surface at ~93% opacity (same alpha in both modes) so the legend
        # reads as a card over the map tiles rather than a hard-edged box;
        # box-shadow direction unchanged -- a soft dark shadow still reads
        # as "lifted" on the dark surface, just less prominently.
        self.surface = chrome["surface"] + "ee"
        self.gridline = chrome["gridline"]
        self.shadow = "0 2px 8px rgba(0,0,0,0.35)" if theme == "dark" else "0 2px 8px rgba(11,11,11,0.12)"


def _marker_color(row: sqlite3.Row, theme: str = "light") -> str:
    return color_for_species_or_pod(row["species"], row["pod_code"], theme=theme)


def _popup_html(row: sqlite3.Row) -> str:
    pod = f" ({row['pod_code']})" if row["pod_code"] else ""
    trusted = "trusted" if row["trusted"] else ("untrusted" if row["trusted"] is not None else "trust unknown")
    return (
        f"<b>{row['species']}{pod}</b><br>"
        f"{row['sighting_date']} {row['sighting_time'] or ''}<br>"
        f"{row['location_name'] or ''}<br>"
        f"<i>{trusted}, source: {row['source']}</i>"
    )


def _pod_codes_of(row: sqlite3.Row) -> list[str]:
    """A sighting's pod_code can be a comma-joined list ('J,L') when a
    report mentions more than one pod -- split it out so filtering can
    check membership rather than exact string equality."""
    raw = row["pod_code"]
    return [p.strip() for p in raw.split(",")] if raw else []


def build_map(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    region: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_miles: float = 15.0,
    species: str | list[str] | None = None,
    pod_codes: list[str] | None = None,
    trusted_only: bool = False,
    theme: str = "light",
) -> folium.Map:
    """Build a folium map of matching sightings. Pass `region` (a known
    place name) OR `lat`/`lon` (an arbitrary point) to also filter by
    location; omit both for all of WA waters within the date range.

    `pod_codes` (2026-09-08, for /map's pod-checkbox filter) narrows orca
    sightings to the selected pod(s) only -- it's applied as a post-filter
    here rather than in storage/db.py because pod_code can be a
    comma-joined multi-pod string ("J,L"), which needs membership
    matching, not a plain SQL equality/IN clause. It never affects
    non-orca rows -- pod is meaningless for other species, same principle
    as the Chinook CPUE chart staying orca-only regardless of the species
    filter on /analysis.

    `theme` (2026-09-08, dashboard dark mode) swaps marker/legend colors
    for the dark-step palette AND darkens the basemap itself -- light OSM
    tiles under a dark page would be its own readability problem. See the
    CSS-filter comment below for why it's a filtered OSM tile rather than
    a dedicated dark tile provider."""
    if region:
        rows = query_region(
            conn, region, radius_miles, start_date=start_date, end_date=end_date,
            species=species, trusted_only=trusted_only,
        )
    elif lat is not None and lon is not None:
        rows = query_point(
            conn, lat, lon, radius_miles, start_date=start_date, end_date=end_date,
            species=species, trusted_only=trusted_only,
        )
    else:
        rows = query_sightings(
            conn, start_date=start_date, end_date=end_date, species=species, trusted_only=trusted_only
        )

    if pod_codes:
        rows = [
            row for row in rows
            if row["species"] != "orca" or any(p in pod_codes for p in _pod_codes_of(row))
        ]

    center = DEFAULT_CENTER
    zoom = DEFAULT_ZOOM
    if region or (lat is not None and lon is not None):
        if rows:
            center = (rows[0]["latitude"], rows[0]["longitude"])
        zoom = 11

    fmap = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    if theme == "dark":
        # Tried CartoDB's dark_matter basemap first -- as of 2026 its free
        # anonymous tile endpoint returns "API KEY REQUIRED" watermark
        # tiles, confirmed live (not just read about), so it's not
        # actually usable without a paid account. Falling back to the
        # standard no-key workaround instead: keep the regular OSM tiles
        # but CSS-invert just the tile pane. This only targets
        # .leaflet-tile-pane, not .leaflet-overlay-pane (where the
        # CircleMarkers/clusters live) or popups, so markers keep their
        # real dark-palette colors instead of getting inverted too.
        fmap.get_root().header.add_child(folium.Element(
            "<style>.leaflet-tile-pane { "
            "filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%); "
            "}</style>"
        ))

    # Marker clustering (2026-09-08): the actual complaint was that the map
    # is unreadable, not just that it lacks filters -- with 1000s of points
    # in a small area (e.g. Admiralty Inlet in-season) markers overlap into
    # an unreadable smear regardless of what's filtered out. MarkerCluster
    # collapses nearby points into numbered clusters that split apart as you
    # zoom in; it clusters on getLatLng() so CircleMarker instances work
    # here same as folium.Marker would, and per-marker color/popup are
    # unaffected -- only the grouping behavior changes.
    cluster = MarkerCluster(name="Sightings").add_to(fmap)

    for row in rows:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        folium.CircleMarker(
            location=(row["latitude"], row["longitude"]),
            radius=6,
            color=_marker_color(row, theme=theme),
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(_popup_html(row), max_width=250),
        ).add_to(cluster)

    fmap.get_root().add_child(_MapLegend(theme=theme))

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
