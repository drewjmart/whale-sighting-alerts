"""
Tests for analysis/correlations.py's cross-series correlation helpers:
tide_height_vs_sightings() (2026-09-08, replacing a tide-height-only chart
that had nothing to compare against) and chinook_cpue_vs_orca_sightings()
(re-tested here after the shared _daily_sighting_counts() extraction, to
lock in that the refactor didn't change its behavior).
"""

from pathlib import Path

import pandas as pd
import pytest

from analysis.correlations import chinook_cpue_vs_orca_sightings, tide_height_vs_sightings
from storage import db


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    yield connection
    connection.close()


def _sighting_with_context(conn, *, sighting_date, species, tide_height_ft=None, chinook_cpue=None,
                            external_id=None, sighting_time="10:00:00"):
    row_id = db.insert_sighting(conn, dict(
        sighting_date=sighting_date, sighting_time=sighting_time, species=species, pod_code=None,
        location_name=None, latitude=47.5763, longitude=-122.4181, trusted=True, source="acartia",
        external_id=external_id, raw_text="",
    ))
    if tide_height_ft is not None or chinook_cpue is not None:
        # tide_height_trend()'s underlying query (query_sightings_with_context,
        # require_tide=True) actually gates on tide_state IS NOT NULL, not
        # tide_height_ft -- match that here or a tide_height_ft-only fixture
        # gets silently excluded.
        db.upsert_environmental_context(conn, row_id, dict(
            chinook_cpue=chinook_cpue, tide_height_ft=tide_height_ft,
            tide_state="flood" if tide_height_ft is not None else None,
            experimental_moon_phase=None,
        ))
    return row_id


def test_tide_height_vs_sightings_merges_tide_and_all_species_counts(conn):
    # Day 1: one orca sighting carrying tide data (tide shows up) plus one
    # humpback sighting with no tide data -- sighting_count must include
    # BOTH (2, not 1), since count isn't limited to only tide-bearing rows.
    _sighting_with_context(conn, sighting_date="2026-09-01", species="orca",
                            tide_height_ft=5.0, external_id="t1")
    _sighting_with_context(conn, sighting_date="2026-09-01", species="humpback", external_id="t2")
    # Day 2: no tide data at all, two sightings.
    _sighting_with_context(conn, sighting_date="2026-09-02", species="orca", external_id="t3")
    _sighting_with_context(conn, sighting_date="2026-09-02", species="orca", external_id="t4")

    result = tide_height_vs_sightings(conn)
    by_date = result.set_index("date")

    assert by_date.loc["2026-09-01", "tide_height_ft"] == 5.0
    assert by_date.loc["2026-09-01", "sighting_count"] == 2
    # Day 2 has no tide row at all -> NaN, not silently dropped from the frame.
    assert by_date.loc["2026-09-02", "sighting_count"] == 2
    assert pd.isna(by_date.loc["2026-09-02", "tide_height_ft"])


def test_tide_height_vs_sightings_respects_species_filter_on_both_series(conn):
    _sighting_with_context(conn, sighting_date="2026-09-01", species="orca",
                            tide_height_ft=4.0, external_id="s1")
    _sighting_with_context(conn, sighting_date="2026-09-01", species="humpback", external_id="s2")

    result = tide_height_vs_sightings(conn, species=["orca"])
    assert len(result) == 1
    assert result.iloc[0]["sighting_count"] == 1  # humpback excluded from the count too


def test_tide_height_vs_sightings_empty_when_no_data(conn):
    result = tide_height_vs_sightings(conn)
    assert result.empty
    assert list(result.columns) == ["date", "tide_height_ft", "sighting_count"]


def test_chinook_cpue_vs_orca_sightings_still_correct_after_shared_helper_refactor(conn):
    _sighting_with_context(conn, sighting_date="2026-09-01", species="orca",
                            chinook_cpue=1200, external_id="c1")
    _sighting_with_context(conn, sighting_date="2026-09-01", species="orca", external_id="c2")
    _sighting_with_context(conn, sighting_date="2026-09-01", species="humpback", external_id="c3")

    result = chinook_cpue_vs_orca_sightings(conn)
    row = result.iloc[0]
    assert row["chinook_cpue"] == 1200
    assert row["sighting_count"] == 2  # orca-only, humpback excluded
