"""
Tests for viz/map.py -- mostly checking the rendered HTML actually contains
what it's supposed to, since folium's real output is what the browser gets.
"""

from pathlib import Path

import pytest

from storage import db
from viz.map import build_map

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
    # Both sightings should still be present as markers, just clustered --
    # each circleMarker must attach to the cluster group variable, not
    # straight to the map, or clustering silently does nothing.
    assert html.count("L.circleMarker(") == 3
    assert html.count(").addTo(marker_cluster_") == 3


def test_build_map_with_no_rows_still_renders(conn):
    fmap = build_map(conn, start_date="2099-01-01")
    html = fmap.get_root().render()
    assert "markerclustergroup" in html.lower() or "MarkerCluster" in html
