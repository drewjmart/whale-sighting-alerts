"""
Tests for viz/colors.py's theme support (dashboard dark mode, 2026-09-08)
and its effect on viz/map.py's rendered output. Contrast itself was
verified separately with a WCAG relative-luminance calculation against
the real #1a1a19 dark surface (see the item-3 commit message for the
numbers) -- these tests check the *wiring*, i.e. that dark theme actually
reaches the rendered map/legend rather than being silently ignored.
"""

from pathlib import Path

import pytest

from storage import db
from viz.colors import (
    POD_COLORS,
    POD_COLORS_DARK,
    SPECIES_COLORS,
    SPECIES_COLORS_DARK,
    chart_chrome,
    color_for_species_or_pod,
    pod_colors,
    species_colors,
)
from viz.map import build_map


def test_pod_colors_and_species_colors_switch_by_theme():
    assert pod_colors("light") == POD_COLORS
    assert pod_colors("dark") == POD_COLORS_DARK
    assert species_colors("light") == SPECIES_COLORS
    assert species_colors("dark") == SPECIES_COLORS_DARK
    # Every dark hue must actually differ from its light counterpart, or
    # "dark mode" would just be silently rendering the light colors.
    for code in ("J", "K", "L", "BIGGS_TRANSIENT"):
        assert POD_COLORS[code] != POD_COLORS_DARK[code]


def test_chart_chrome_dark_uses_the_real_dark_surface():
    chrome = chart_chrome("dark")
    assert chrome["surface"] == "#1a1a19"  # the exact surface the contrast check was run against
    assert chrome["ink_primary"] == "#ffffff"
    assert chrome["surface"] != chart_chrome("light")["surface"]


def test_color_for_species_or_pod_theme_default_is_light():
    assert color_for_species_or_pod("orca", "J") == color_for_species_or_pod("orca", "J", theme="light")
    assert color_for_species_or_pod("orca", "J", theme="dark") == POD_COLORS_DARK["J"]


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    db.insert_sightings(connection, [
        dict(sighting_date="2026-08-05", sighting_time="10:00:00", species="orca", pod_code="J",
             location_name="Alki Point", latitude=47.5763, longitude=-122.4181, trusted=True,
             source="acartia", external_id="t1", raw_text="J pod"),
    ])
    yield connection
    connection.close()


def test_build_map_dark_theme_inverts_tiles_and_uses_dark_marker_color(conn):
    # CartoDB's free dark_matter tiles now require a paid API key (confirmed
    # live -- the anonymous endpoint serves "API KEY REQUIRED" watermark
    # tiles), so dark mode darkens the map by CSS-inverting the regular OSM
    # tile pane instead, scoped to .leaflet-tile-pane only so markers/popups
    # (a different Leaflet pane) aren't inverted along with the basemap.
    fmap = build_map(conn, theme="dark")
    html = fmap.get_root().render()
    assert "leaflet-tile-pane" in html and "invert(100%)" in html
    assert POD_COLORS_DARK["J"] in html
    assert POD_COLORS["J"] not in html  # light hue must not leak into the dark render


def test_build_map_light_theme_has_no_tile_filter_and_uses_light_marker_color(conn):
    fmap = build_map(conn, theme="light")
    html = fmap.get_root().render()
    assert "openstreetmap" in html.lower()
    assert "leaflet-tile-pane" not in html  # the invert filter is dark-only
    assert POD_COLORS["J"] in html
