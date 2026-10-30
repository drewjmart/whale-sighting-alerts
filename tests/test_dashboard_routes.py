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
