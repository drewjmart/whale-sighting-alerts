"""
Route-level tests for dashboard/app.py -- renders real pages against a temp
database. Added after the home page's 24-hour card was found showing a raw
species code ("gray_whale") that every earlier friendly-names check missed:
it never appeared while that card was empty, and no test rendered it with
data in it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from dashboard import app as dashboard_app
from storage import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    db.insert_sightings(conn, [
        dict(sighting_date=one_hour_ago.date().isoformat(), sighting_time=one_hour_ago.strftime("%H:%M:%S"),
             species="gray_whale", pod_code=None, location_name=None,
             latitude=47.5763, longitude=-122.4181, trusted=True,
             source="acartia", external_id="g1", raw_text=""),
    ])
    conn.close()
    monkeypatch.setattr(dashboard_app, "_conn", lambda: db.get_connection(db_path))
    return dashboard_app.app.test_client()


def test_home_page_24h_card_shows_friendly_species_not_raw_code(client):
    html = client.get("/").get_data(as_text=True)
    assert "Gray whale" in html
    assert "gray_whale" not in html


# ── last-30-days default (2026-10-29) ─────────────────────────────────────

@pytest.fixture()
def window_client(tmp_path, monkeypatch):
    """Three sightings: one dated today in UTC, one 5 days ago, one 60 days
    ago. The first guards the UTC point -- it must show up in the default
    view even when the machine's local date is a day behind UTC."""
    today = dashboard_app._today()
    db_path = tmp_path / "window.sqlite3"
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    db.insert_sightings(conn, [
        dict(sighting_date=(today - timedelta(days=ago)).isoformat(), sighting_time="12:00:00",
             species="orca", pod_code=None, location_name=None, latitude=47.5763, longitude=-122.4181,
             trusted=True, source="acartia", external_id=ext, raw_text="")
        for ext, ago in [("today", 0), ("recent", 5), ("old", 60)]
    ])
    conn.close()
    monkeypatch.setattr(dashboard_app, "_conn", lambda: db.get_connection(db_path))
    return dashboard_app.app.test_client()


def _markers(client, query=""):
    return client.get(f"/map/frame{query}").get_data(as_text=True).count("L.circleMarker(")


def test_map_defaults_to_last_30_days_including_todays_utc_sightings(window_client):
    assert _markers(window_client) == 2  # today + 5 days ago; the 60-day-old one is out


def test_map_all_time_includes_everything(window_client):
    assert _markers(window_client, "?start_date=&end_date=") == 3


def test_map_explicit_range_overrides_the_default(window_client):
    today = dashboard_app._today()
    start = (today - timedelta(days=90)).isoformat()
    assert _markers(window_client, f"?start_date={start}&end_date={today.isoformat()}") == 3


def test_map_page_forwards_all_time_to_the_iframe(window_client):
    # If the page didn't forward present-but-empty dates, the iframe would
    # see none and silently snap back to the 30-day default.
    html = window_client.get("/map?start_date=&end_date=").get_data(as_text=True)
    assert "/map/frame?start_date=&amp;end_date=" in html


def test_map_page_shows_30_day_inputs_and_highlights_the_shortcut_by_default(window_client):
    html = window_client.get("/map").get_data(as_text=True)
    start = (dashboard_app._today() - timedelta(days=30)).isoformat()
    assert f'value="{start}"' in html
    assert 'class="date-shortcut active"' in html


def test_reset_link_only_appears_when_something_differs_from_the_default(window_client):
    assert "Reset filters" not in window_client.get("/map").get_data(as_text=True)
    assert "Reset filters" in window_client.get("/map?species=orca").get_data(as_text=True)
    assert "Reset filters" in window_client.get("/map?start_date=&end_date=").get_data(as_text=True)
    assert "Reset filters" not in window_client.get("/analysis").get_data(as_text=True)
    assert "Reset filters" in window_client.get("/analysis?species=orca").get_data(as_text=True)


def test_analysis_defaults_to_30_days_and_all_time_clears_the_inputs(window_client):
    today = dashboard_app._today()
    html = window_client.get("/analysis").get_data(as_text=True)
    assert f'value="{today.isoformat()}"' in html
    html_all = window_client.get("/analysis?start_date=&end_date=").get_data(as_text=True)
    assert f'value="{today.isoformat()}"' not in html_all
