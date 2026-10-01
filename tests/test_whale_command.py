"""
Tests for discord_bot/whale_command.py::build_activity_summary() -- the
Discord-independent business logic (fetch + format), stubbing
AcartiaClient so no real network call or bot token is needed.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from discord_bot.whale_command import build_activity_summary
from ingestion.acartia_client import AcartiaClientError, AcartiaSighting


def _sighting(entry_id, created_utc, species_raw="Orca", lat=47.5763, lon=-122.4181, comments=""):
    return AcartiaSighting(
        entry_id=entry_id, species_raw=species_raw, created_utc=created_utc,
        latitude=lat, longitude=lon, trusted=True, comments=comments,
        data_source_entity="acartia", data_source_witness="public",
        no_sighted=1, photo_url="",
    )


@pytest.fixture()
def mock_client():
    with patch("discord_bot.whale_command.AcartiaClient") as MockClient:
        instance = MockClient.return_value
        yield instance


def test_sightings_shown_most_recent_first(mock_client):
    # Deliberately fed in ascending order, matching Acartia's real API
    # order -- the function must re-sort, not trust the input order.
    mock_client.get_current_sightings.return_value = [
        _sighting("a1", datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)),
        _sighting("a2", datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)),
        _sighting("a3", datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)),
    ]
    result = build_activity_summary()
    lines = [l for l in result.splitlines() if l.startswith("- ")]
    # 10:00 should come first, then 09:00, then 08:00.
    assert "10:00" in lines[0]
    assert "09:00" in lines[1]
    assert "08:00" in lines[2]


def test_truncation_keeps_the_most_recent_not_the_first_fetched():
    # Regression case: 12 sightings, fed in ascending order (oldest first,
    # matching the real API). Before the fix, slicing [:10] on unsorted
    # input would keep the 10 OLDEST and drop the 2 most recent into
    # "...and N more" -- backwards for a "current activity" command.
    sightings = [
        _sighting(f"s{i}", datetime(2026, 10, 1, i, 0, tzinfo=timezone.utc))
        for i in range(12)  # hours 0..11, ascending
    ]
    with patch("discord_bot.whale_command.AcartiaClient") as MockClient:
        MockClient.return_value.get_current_sightings.return_value = sightings
        result = build_activity_summary()

    lines = [l for l in result.splitlines() if l.startswith("- ")]
    assert len(lines) == 10
    # The 10 shown must be the 10 most recent (hours 11 down to 2), with
    # the 2 oldest (hours 0 and 1) the ones left out of the overflow note.
    assert "11:00" in lines[0]
    assert "02:00" in lines[-1]
    assert "and 2 more" in result


def test_region_filter_applied_after_sorting_still_works(mock_client):
    alki = _sighting(
        "near", datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        lat=47.5763, lon=-122.4181, comments="seen from the ferry dock",
    )
    far_away = _sighting(
        "far", datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        lat=48.9, lon=-123.5, comments="seen near the San Juans",
    )
    # Fed newest-first on purpose -- the region filter runs after sorting,
    # so this also confirms filtering doesn't depend on fetch order.
    mock_client.get_current_sightings.return_value = [far_away, alki]

    result = build_activity_summary(region="alki point")
    assert "(1 report(s))" in result
    assert "seen from the ferry dock" in result
    assert "seen near the San Juans" not in result


def test_unknown_region_returns_a_warning_not_a_crash(mock_client):
    mock_client.get_current_sightings.return_value = []
    result = build_activity_summary(region="nonexistent place")
    assert "Unknown region" in result


def test_no_sightings_is_an_honest_empty_message(mock_client):
    mock_client.get_current_sightings.return_value = []
    result = build_activity_summary()
    assert "No current whale activity" in result


def test_acartia_error_is_reported_not_raised(mock_client):
    mock_client.get_current_sightings.side_effect = AcartiaClientError("timed out")
    result = build_activity_summary()
    assert "Couldn't reach Acartia" in result
