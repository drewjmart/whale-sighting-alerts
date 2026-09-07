"""
Tests for analysis/pivots.py's home-page KPI functions (2026-09-08):
season total + week-over-week change, most active location, days since
last sighting per species, and the orca pod resolution rate.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysis.pivots import (
    days_since_last_sighting,
    most_active_location,
    orca_pod_resolution_rate,
    season_total_with_change,
)
from storage import db

FIXED_NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)  # a Friday, meteorological fall


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    connection = db.get_connection(db_path)
    yield connection
    connection.close()


def _record(sighting_date, species, lat=47.5763, lon=-122.4181, pod_code=None, external_id=None,
            sighting_time="10:00:00"):
    return dict(
        sighting_date=sighting_date, sighting_time=sighting_time, species=species, pod_code=pod_code,
        location_name=None, latitude=lat, longitude=lon, trusted=True, source="acartia",
        external_id=external_id, raw_text="",
    )


# ── season_total_with_change ─────────────────────────────────────────────

def test_season_total_counts_only_current_season_and_year(conn):
    db.insert_sightings(conn, [
        _record("2026-09-01", "orca", external_id="s1"),   # fall 2026 -- counts
        _record("2026-09-03", "orca", external_id="s2"),   # fall 2026 -- counts
        _record("2026-06-15", "orca", external_id="s3"),   # summer 2026 -- doesn't count
        _record("2025-09-02", "orca", external_id="s4"),   # fall 2025, same months, wrong year
    ])
    result = season_total_with_change(conn, now=FIXED_NOW)
    assert result["season"] == "fall"
    assert result["season_total"] == 2


def test_season_total_week_over_week_change_computed_correctly(conn):
    # FIXED_NOW is 2026-09-04. Last 7 days: 2026-08-28..2026-09-04.
    # Prior 7 days: 2026-08-21..2026-08-27.
    records = (
        [_record("2026-09-01", "orca", external_id=f"cw{i}") for i in range(4)]
        + [_record("2026-08-25", "orca", external_id=f"pw{i}") for i in range(2)]
    )
    db.insert_sightings(conn, records)
    result = season_total_with_change(conn, now=FIXED_NOW)
    assert result["current_week_count"] == 4
    assert result["prior_week_count"] == 2
    assert result["change_pct"] == 100.0  # doubled


def test_season_total_change_pct_is_none_not_infinite_when_prior_week_empty(conn):
    db.insert_sightings(conn, [_record("2026-09-01", "orca", external_id="cw1")])
    result = season_total_with_change(conn, now=FIXED_NOW)
    assert result["prior_week_count"] == 0
    assert result["change_pct"] is None


# ── most_active_location ─────────────────────────────────────────────────

def test_most_active_location_picks_the_highest_count(conn):
    db.insert_sightings(conn, [
        _record("2026-09-04", "orca", lat=47.5763, lon=-122.4181, external_id="a1", sighting_time="09:00:00"),
        _record("2026-09-04", "orca", lat=47.5763, lon=-122.4181, external_id="a2", sighting_time="10:00:00"),
        _record("2026-09-04", "humpback", lat=48.5343, lon=-123.0885, external_id="a3", sighting_time="11:00:00"),
    ])
    result = most_active_location(conn, now=FIXED_NOW)
    assert result["location"] == "Alki Point"
    assert result["count"] == 2


def test_most_active_location_is_none_not_a_guess_when_window_is_empty(conn):
    db.insert_sightings(conn, [_record("2026-08-01", "orca", external_id="old")])  # weeks before FIXED_NOW
    result = most_active_location(conn, now=FIXED_NOW)
    assert result == {"location": None, "count": 0, "window_hours": 24}


# ── days_since_last_sighting ──────────────────────────────────────────────

def test_days_since_last_sighting_per_species(conn):
    db.insert_sightings(conn, [
        _record("2026-09-02", "orca", external_id="d1"),      # 2 days before FIXED_NOW
        _record("2026-08-25", "humpback", external_id="d2"),  # 10 days before
    ])
    result = days_since_last_sighting(conn, now=FIXED_NOW)
    assert result["orca"] == 2
    assert result["humpback"] == 10
    assert result["dolphin"] is None  # never sighted -- not 0, not a huge fake number


# ── orca_pod_resolution_rate ──────────────────────────────────────────────

def test_orca_pod_resolution_rate_counts_identified_vs_not(conn):
    db.insert_sightings(conn, [
        _record("2026-09-01", "orca", pod_code="J", external_id="r1"),
        _record("2026-09-01", "orca", pod_code="J,L", external_id="r2"),        # multi-pod, still resolved
        _record("2026-09-01", "orca", pod_code="SRKW_UNSPECIFIED", external_id="r3"),
        _record("2026-09-01", "orca", pod_code="UNKNOWN", external_id="r4"),
        _record("2026-09-01", "orca", pod_code=None, external_id="r5"),
        _record("2026-09-01", "humpback", external_id="r6"),  # not orca -- excluded entirely
    ])
    result = orca_pod_resolution_rate(conn)
    assert result["total"] == 5
    assert result["resolved"] == 2
    assert result["unresolved"] == 3
    assert result["resolution_rate_pct"] == 40.0


def test_orca_pod_resolution_rate_handles_zero_orca_sightings(conn):
    db.insert_sightings(conn, [_record("2026-09-01", "humpback", external_id="h1")])
    result = orca_pod_resolution_rate(conn)
    assert result == {"resolved": 0, "unresolved": 0, "total": 0, "resolution_rate_pct": None}
