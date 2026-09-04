"""
Tests for analysis/pivots.py::recent_24h_summary() and its
normalization/location_geocoder.py::nearest_known_location() dependency.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysis.pivots import recent_24h_summary
from normalization.location_geocoder import nearest_known_location
from storage import db

FIXED_NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    yield connection
    connection.close()


def _record(sighting_date, sighting_time, species, lat, lon, external_id):
    return dict(
        sighting_date=sighting_date, sighting_time=sighting_time, species=species, pod_code=None,
        location_name=None, latitude=lat, longitude=lon, trusted=True, source="acartia",
        external_id=external_id, raw_text="",
    )


def test_recent_24h_summary_includes_only_the_real_window(conn):
    # Alki Point coordinates for all three -- only sighting_time varies.
    db.insert_sightings(conn, [
        _record("2026-09-04", "11:00:00", "orca", 47.5763, -122.4181, "a1"),  # 1h before FIXED_NOW -- in window
        _record("2026-09-03", "13:00:00", "orca", 47.5763, -122.4181, "a2"),  # 23h before -- in window
        _record("2026-09-03", "11:00:00", "orca", 47.5763, -122.4181, "a3"),  # 25h before -- OUT of window
        _record("2026-09-04", "13:00:00", "orca", 47.5763, -122.4181, "a4"),  # 1h AFTER FIXED_NOW -- OUT of window
    ])

    result = recent_24h_summary(conn, now=FIXED_NOW)

    assert result["total"] == 2
    assert result["groups"] == [{"species": "orca", "location": "Alki Point", "count": 2}]


def test_recent_24h_summary_groups_by_species_and_location(conn):
    db.insert_sightings(conn, [
        _record("2026-09-04", "10:00:00", "orca", 47.5763, -122.4181, "b1"),      # Alki Point
        _record("2026-09-04", "10:30:00", "orca", 47.5763, -122.4181, "b2"),      # Alki Point
        _record("2026-09-04", "11:00:00", "humpback", 47.5763, -122.4181, "b3"),  # Alki Point, different species
        _record("2026-09-04", "11:30:00", "orca", 38.95, -123.737, "b4"),         # far away -- unmapped
    ])

    result = recent_24h_summary(conn, now=FIXED_NOW)

    assert result["total"] == 4
    groups_by_key = {(g["species"], g["location"]): g["count"] for g in result["groups"]}
    assert groups_by_key[("orca", "Alki Point")] == 2
    assert groups_by_key[("humpback", "Alki Point")] == 1
    assert groups_by_key[("orca", "an unmapped location")] == 1


def test_recent_24h_summary_empty_window_is_honest_not_an_error(conn):
    db.insert_sightings(conn, [
        _record("2026-08-01", "10:00:00", "orca", 47.5763, -122.4181, "c1"),  # weeks before FIXED_NOW
    ])

    result = recent_24h_summary(conn, now=FIXED_NOW)

    assert result["total"] == 0
    assert result["groups"] == []


def test_recent_24h_summary_handles_null_sighting_time(conn):
    # sighting_time is nullable in the schema -- must not crash on it.
    db.insert_sightings(conn, [
        dict(sighting_date="2026-09-04", sighting_time=None, species="orca",
             pod_code=None, location_name=None, latitude=47.5763, longitude=-122.4181,
             trusted=True, source="orca_network", external_id=None, raw_text=""),
    ])

    result = recent_24h_summary(conn, now=FIXED_NOW)
    assert result["total"] == 1  # treated as midnight UTC that day -- within the window


def test_nearest_known_location_within_range():
    assert nearest_known_location(47.5763, -122.4181) == "Alki Point"


def test_nearest_known_location_beyond_range_is_none_not_a_guess():
    # Bodega Bay, CA -- a real coordinate that appears in live Acartia data
    # but is nowhere near any Salish Sea viewpoint.
    assert nearest_known_location(38.95, -123.737) is None


def test_nearest_known_location_respects_custom_max_distance():
    # A point far outside the default 15mi radius resolves to nothing by
    # default, but should resolve to *something* once the allowed radius
    # is widened past the real distance -- which specific place wins isn't
    # the point here, just that the cutoff is actually respected both ways.
    far_point = (38.95, -123.737)
    assert nearest_known_location(*far_point) is None
    assert nearest_known_location(*far_point, max_distance_miles=5000) is not None
