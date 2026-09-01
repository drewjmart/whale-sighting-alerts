"""
Integration test for analysis/pivots.py -- builds a temp SQLite DB from
synthetic-but-realistic records (shaped like real normalized Acartia
output) and checks the three required pivot tables come out right.
"""

from pathlib import Path

import pytest

from analysis.pivots import location_by_species, pod_by_month, species_by_month
from storage import db

FIXTURE_RECORDS = [
    # Two J pod sightings in August, one K, one comma-joined J+L, one UNKNOWN orca.
    dict(sighting_date="2026-08-05", sighting_time="10:00:00", species="orca", pod_code="J",
         location_name="Alki Point", latitude=47.5763, longitude=-122.4181, trusted=True,
         source="acartia", external_id="a1", raw_text="J pod northbound"),
    dict(sighting_date="2026-08-12", sighting_time="11:00:00", species="orca", pod_code="J",
         location_name="Alki Point", latitude=47.5763, longitude=-122.4181, trusted=True,
         source="acartia", external_id="a2", raw_text="J pod again"),
    dict(sighting_date="2026-08-20", sighting_time="09:00:00", species="orca", pod_code="K",
         location_name="San Juan Island", latitude=48.5343, longitude=-123.0885, trusted=True,
         source="acartia", external_id="a3", raw_text="K pod"),
    dict(sighting_date="2026-09-01", sighting_time="14:00:00", species="orca", pod_code="J,L",
         location_name="Admiralty Inlet", latitude=48.15, longitude=-122.70, trusted=True,
         source="acartia", external_id="a4", raw_text="J and L pods"),
    dict(sighting_date="2026-09-03", sighting_time="08:00:00", species="orca", pod_code="UNKNOWN",
         location_name=None, latitude=47.9, longitude=-122.4, trusted=None,
         source="acartia", external_id="a5", raw_text="orca, no other detail"),
    # Non-orca species, no pod code.
    dict(sighting_date="2026-08-15", sighting_time="12:00:00", species="humpback", pod_code=None,
         location_name="Elliott Bay", latitude=47.6062, longitude=-122.3599, trusted=True,
         source="acartia", external_id="a6", raw_text="humpback feeding"),
    dict(sighting_date="2026-09-02", sighting_time="16:00:00", species="gray_whale", pod_code=None,
         location_name="Elliott Bay", latitude=47.6062, longitude=-122.3599, trusted=False,
         source="orca_network", external_id=None, raw_text="gray whale surfacing"),
]


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    db.insert_sightings(connection, FIXTURE_RECORDS)
    yield connection
    connection.close()


def test_pod_by_month_counts_and_explodes_multi_pod_records(conn):
    result = pod_by_month(conn)

    assert "2026-08" in result.columns
    assert "2026-09" in result.columns

    # J appears 3 times in August->September: two solo August records + one
    # September "J,L" record that must be exploded so it counts for BOTH J and L.
    assert result.loc["J", "2026-08"] == 2
    assert result.loc["J", "2026-09"] == 1
    assert result.loc["L", "2026-09"] == 1
    assert result.loc["K", "2026-08"] == 1
    assert result.loc["UNKNOWN", "2026-09"] == 1


def test_species_by_month_covers_all_species(conn):
    result = species_by_month(conn)

    assert set(result.index) == {"orca", "humpback", "gray_whale"}
    assert result.loc["orca", "2026-08"] == 3  # two J + one K
    assert result.loc["orca", "2026-09"] == 2  # J,L record + UNKNOWN record
    assert result.loc["humpback", "2026-08"] == 1
    assert result.loc["gray_whale", "2026-09"] == 1


def test_location_by_species_groups_missing_location(conn):
    result = location_by_species(conn)

    assert result.loc["Alki Point", "orca"] == 2
    assert result.loc["Elliott Bay", "humpback"] == 1
    assert result.loc["Elliott Bay", "gray_whale"] == 1
    # The one record with location_name=None must not be dropped.
    assert "unknown_location" in result.index
    assert result.loc["unknown_location", "orca"] == 1


def test_pivots_never_crash_on_empty_db(tmp_path: Path):
    empty_db = tmp_path / "empty.sqlite3"
    db.init_db(empty_db)
    empty_conn = db.get_connection(empty_db)

    assert pod_by_month(empty_conn).empty
    assert species_by_month(empty_conn).empty
    assert location_by_species(empty_conn).empty
