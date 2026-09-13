"""
Tests for viz/map.py -- mostly checking the rendered HTML actually contains
what it's supposed to, since folium's real output is what the browser gets.
"""

from pathlib import Path

import pytest

from storage import db
from viz.map import build_map, orca_pod_tracks

FIXTURE_RECORDS = [
    dict(sighting_date="2026-08-05", sighting_time="10:00:00", species="orca", pod_code="J",
         location_name="Alki Point", latitude=47.5763, longitude=-122.4181, trusted=True,
         source="acartia", external_id="m1", raw_text="J pod northbound"),
    dict(sighting_date="2026-08-12", sighting_time="11:00:00", species="orca", pod_code="J",
         location_name="Alki Point", latitude=47.5763, longitude=-122.4181, trusted=True,
         source="acartia", external_id="m2", raw_text="J pod again"),
    dict(sighting_date="2026-08-20", sighting_time="09:00:00", species="humpback", pod_code=None,
         location_name="Elliott Bay", latitude=47.6062, longitude=-122.3599, trusted=False,
         source="orca_network", external_id="m3", raw_text="humpback feeding"),
    dict(sighting_date="2026-09-01", sighting_time="14:00:00", species="orca", pod_code="K",
         location_name="San Juan Island", latitude=48.5343, longitude=-123.0885, trusted=None,
         source="orca_network", external_id="m4", raw_text="K pod, unverified"),
    dict(sighting_date="2026-09-02", sighting_time="08:00:00", species="orca", pod_code="J,L",
         location_name="Admiralty Inlet", latitude=48.15, longitude=-122.70, trusted=True,
         source="acartia", external_id="m5", raw_text="J and L pods"),
]


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    db.insert_sightings(connection, FIXTURE_RECORDS)
    yield connection
    connection.close()


def test_build_map_clusters_markers_via_markercluster(conn):
    # The real fix for "map is unreadable" -- markers must be added to a
    # MarkerCluster layer, not straight onto the map, so the rendered HTML
    # has to actually reference Leaflet.markercluster.
    fmap = build_map(conn)
    html = fmap.get_root().render()

    assert "markerclustergroup" in html.lower() or "MarkerCluster" in html
    # All 5 fixture sightings should still be present as markers, just
    # clustered -- each circleMarker must attach to the cluster group
    # variable, not straight to the map, or clustering silently does nothing.
    assert html.count("L.circleMarker(") == 5
    assert html.count(").addTo(marker_cluster_") == 5


def test_build_map_with_no_rows_still_renders(conn):
    fmap = build_map(conn, start_date="2099-01-01")
    html = fmap.get_root().render()
    assert "markerclustergroup" in html.lower() or "MarkerCluster" in html


def test_build_map_pod_filter_only_affects_orca(conn):
    # 5 fixture rows: 2x J-pod orca, 1x humpback, 1x K-pod orca, 1x J+L orca.
    # Filtering to pod=J should keep both J-pod rows, the J+L row (J is one
    # of its pods), and the humpback (pod filter must not touch non-orca
    # rows) -- but drop the K-only orca row. That's 4 of 5.
    fmap = build_map(conn, pod_codes=["J"])
    html = fmap.get_root().render()
    assert html.count("L.circleMarker(") == 4


def test_build_map_trusted_only_excludes_untrusted_and_unknown(conn):
    # Of the 5 fixture rows: 3 are trusted=True, 1 is trusted=False, 1 is
    # trusted=None (no trust concept for that source). "Trusted only"
    # should keep just the 3 explicitly-trusted rows.
    fmap = build_map(conn, trusted_only=True)
    html = fmap.get_root().render()
    assert html.count("L.circleMarker(") == 3


def test_build_map_species_filter_accepts_a_list(conn):
    fmap = build_map(conn, species=["humpback"])
    html = fmap.get_root().render()
    assert html.count("L.circleMarker(") == 1


def test_build_map_tracks_are_opt_in_and_off_by_default(conn):
    # show_tracks defaults to False -- checked against the real data, an
    # unfiltered view produces a dense, hard-to-read tangle of lines (see
    # build_map's docstring), so tracks must be explicitly requested.
    db.insert_sightings(conn, [
        dict(sighting_date="2026-09-01", sighting_time="08:00:00", species="orca", pod_code="K",
             location_name=None, latitude=48.5, longitude=-123.0, trusted=True, source="acartia",
             external_id="track1", raw_text=""),
        dict(sighting_date="2026-09-02", sighting_time="08:00:00", species="orca", pod_code="K",
             location_name=None, latitude=48.6, longitude=-123.1, trusted=True, source="acartia",
             external_id="track2", raw_text=""),
    ])
    html_default = build_map(conn).get_root().render()
    assert "textpath" not in html_default.lower()

    html_with_tracks = build_map(conn, show_tracks=True).get_root().render()
    assert "textpath" in html_with_tracks.lower()


def _row(sighting_date, sighting_time, species, pod_code, lat, lon):
    return dict(
        sighting_date=sighting_date, sighting_time=sighting_time, species=species, pod_code=pod_code,
        location_name=None, latitude=lat, longitude=lon, trusted=True, source="acartia",
        external_id=None, raw_text="",
    )


def test_orca_pod_tracks_connects_same_pod_within_the_gap_window():
    rows = [
        _row("2026-09-01", "08:00:00", "orca", "J", 47.0, -122.0),
        _row("2026-09-02", "08:00:00", "orca", "J", 47.5, -122.2),  # 24h later -- connects
    ]
    tracks = orca_pod_tracks(rows)
    assert tracks["J"] == [[(47.0, -122.0), (47.5, -122.2)]]


def test_orca_pod_tracks_splits_on_a_gap_over_the_threshold():
    rows = [
        _row("2026-09-01", "08:00:00", "orca", "J", 47.0, -122.0),
        _row("2026-09-10", "08:00:00", "orca", "J", 47.5, -122.2),  # 9 days later -- separate visit
    ]
    tracks = orca_pod_tracks(rows, max_gap_hours=48)
    assert "J" not in tracks  # neither point has a same-segment partner -> no 2+-point segment


def test_orca_pod_tracks_excludes_unspecified_and_unknown_pods():
    rows = [
        _row("2026-09-01", "08:00:00", "orca", "SRKW_UNSPECIFIED", 47.0, -122.0),
        _row("2026-09-01", "09:00:00", "orca", "SRKW_UNSPECIFIED", 47.1, -122.1),
        _row("2026-09-01", "08:00:00", "orca", "UNKNOWN", 47.0, -122.0),
        _row("2026-09-01", "09:00:00", "orca", "UNKNOWN", 47.1, -122.1),
    ]
    assert orca_pod_tracks(rows) == {}


def test_orca_pod_tracks_multi_pod_sighting_contributes_to_both_tracks():
    rows = [
        _row("2026-09-01", "08:00:00", "orca", "J", 47.0, -122.0),
        _row("2026-09-01", "10:00:00", "orca", "J,L", 47.2, -122.1),
        _row("2026-09-02", "08:00:00", "orca", "L", 47.4, -122.3),
    ]
    tracks = orca_pod_tracks(rows)
    assert tracks["J"] == [[(47.0, -122.0), (47.2, -122.1)]]
    assert tracks["L"] == [[(47.2, -122.1), (47.4, -122.3)]]


def test_orca_pod_tracks_ignores_non_orca_and_missing_coordinates():
    rows = [
        _row("2026-09-01", "08:00:00", "humpback", None, 47.0, -122.0),
        _row("2026-09-01", "09:00:00", "orca", "J", None, None),
        _row("2026-09-01", "10:00:00", "orca", "J", 47.1, -122.1),
    ]
    assert orca_pod_tracks(rows) == {}  # only 1 valid J point -- can't form a 2-point segment
