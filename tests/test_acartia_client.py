"""
Tests for ingestion/acartia_client.py.

Two kinds, deliberately not blended:
- Pure parsing tests (AcartiaSighting.from_raw) -- no network, run every
  time, cover the real quirks confirmed in a live response (lat/lon and
  no_sighted arrive as strings, not numbers).
- One live integration test against the real endpoint -- this project's
  established pattern throughout is verifying against real data rather
  than only mocks; skipped automatically (not failed) if the network
  isn't reachable, so it doesn't break an offline/CI run.
"""

import pytest

from ingestion.acartia_client import AcartiaClient, AcartiaClientError, AcartiaSighting

# A real raw record shape, taken from an actual live API response
# (2026-08-27) -- see acartia_client.py's module docstring.
REAL_SAMPLE_RAW = {
    "ssemmi_id": "SPOTTER 258659",
    "data_source_name": "Spotter-API",
    "data_source_entity": "Conserve.io",
    "data_source_id": 258659,
    "created": "2026-08-26 00:30:00",
    "photo_url": "",
    "no_sighted": "1",  # string, not int -- confirmed live quirk
    "latitude": "47.881",  # string, not float -- confirmed live quirk
    "longitude": "-122.50829",
    "type": "Orca",
    "data_source_witness": "whalealertoa",
    "trusted": 1,
    "data_source_comments": "Solo male. Heading north fast past Pilot Point.",
    "profile": {"name": "spotter"},
    "entry_id": "bce3e660-b1a8-46a5-bc9a-c1417ebc37bc",
}


def test_from_raw_parses_real_sample_shape():
    sighting = AcartiaSighting.from_raw(REAL_SAMPLE_RAW)

    assert sighting.entry_id == "bce3e660-b1a8-46a5-bc9a-c1417ebc37bc"
    assert sighting.species_raw == "Orca"
    assert sighting.latitude == pytest.approx(47.881)
    assert sighting.longitude == pytest.approx(-122.50829)
    assert sighting.no_sighted == 1
    assert sighting.trusted is True
    assert sighting.created_utc.year == 2026
    assert sighting.created_utc.month == 8
    assert sighting.created_utc.day == 26


def test_from_raw_coerces_string_lat_lon_and_no_sighted():
    # The confirmed live quirk this test exists to guard against: if
    # Acartia ever stopped sending these as strings (or a future change
    # broke the coercion), this would catch it.
    raw = dict(REAL_SAMPLE_RAW, latitude="48.0", longitude="-123.0", no_sighted="3")
    sighting = AcartiaSighting.from_raw(raw)
    assert isinstance(sighting.latitude, float)
    assert isinstance(sighting.longitude, float)
    assert isinstance(sighting.no_sighted, int)
    assert sighting.no_sighted == 3


def test_from_raw_missing_no_sighted_is_none_not_a_crash():
    raw = dict(REAL_SAMPLE_RAW)
    raw.pop("no_sighted")
    sighting = AcartiaSighting.from_raw(raw)
    assert sighting.no_sighted is None


def test_from_raw_bad_timestamp_raises_clear_error():
    raw = dict(REAL_SAMPLE_RAW, created="not-a-timestamp")
    with pytest.raises(AcartiaClientError):
        AcartiaSighting.from_raw(raw)


def test_from_raw_bad_lat_lon_raises_clear_error():
    raw = dict(REAL_SAMPLE_RAW, latitude="not-a-number")
    with pytest.raises(AcartiaClientError):
        AcartiaSighting.from_raw(raw)


def test_from_raw_missing_optional_fields_default_sensibly():
    minimal = {
        "created": "2026-08-26 00:30:00",
        "latitude": "47.0",
        "longitude": "-122.0",
    }
    sighting = AcartiaSighting.from_raw(minimal)
    assert sighting.entry_id == ""
    assert sighting.species_raw == ""
    assert sighting.comments == ""
    assert sighting.trusted is None


# ── Live integration test ────────────────────────────────────────────────

def test_get_current_sightings_against_real_live_api():
    """Confirms the actual endpoint still works and returns parseable data
    -- not just that our parsing logic is internally consistent. Skips
    (doesn't fail) if the network isn't reachable, since that's an
    environment fact, not a code defect."""
    try:
        client = AcartiaClient()
        sightings = client.get_current_sightings()
    except AcartiaClientError as exc:
        pytest.skip(f"Acartia API not reachable in this environment: {exc}")

    assert isinstance(sightings, list)
    # The last 7 days across the whole Salish Sea domain; zero is
    # plausible but very unlikely -- if this starts failing, it's worth
    # a human looking at whether the API contract changed.
    if sightings:
        first = sightings[0]
        assert isinstance(first, AcartiaSighting)
        assert -90 <= first.latitude <= 90
        assert -180 <= first.longitude <= 180
