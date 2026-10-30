"""
Tests for dashboard/app.py's date-range helpers: the "Last 7/14/30 days"
(+ "All time") shortcuts shared by /map and /analysis (2026-09-13), and the
last-30-days default both pages open on (2026-10-29).

All "today" math goes through dashboard.app._today() (UTC) rather than
date.today() -- sightings are stored in UTC, and the local date can be a
day behind in the evening.
"""

from datetime import timedelta

from dashboard.app import (
    DEFAULT_RANGE_DAYS,
    _active_shortcut_days,
    _date_range_from_args,
    _date_shortcut_urls,
    _is_default_range,
    _today,
)


def test_date_shortcut_urls_preserves_other_params():
    urls = _date_shortcut_urls("/map", {"species": ["orca"], "trust": "trusted"})
    today = _today()

    assert set(urls.keys()) == {7, 14, 30, "all"}
    for days in (7, 14, 30):
        url = urls[days]
        assert url.startswith("/map?")
        assert f"start_date={(today - timedelta(days=days)).isoformat()}" in url
        assert f"end_date={today.isoformat()}" in url
    for url in urls.values():
        assert "species=orca" in url
        assert "trust=trusted" in url


def test_date_shortcut_urls_with_no_other_filters():
    urls = _date_shortcut_urls("/analysis", {})
    assert urls[7].startswith("/analysis?start_date=")


def test_all_time_shortcut_sends_present_but_empty_date_params():
    # Absent params mean "default to 30 days"; all-time has to be spelled
    # as present-but-empty or it would just snap back to the default.
    assert _date_shortcut_urls("/map", {})["all"] == "/map?start_date=&end_date="


def test_active_shortcut_days_matches_exact_range():
    today = _today()
    assert _active_shortcut_days((today - timedelta(days=7)).isoformat(), today.isoformat()) == 7
    assert _active_shortcut_days((today - timedelta(days=14)).isoformat(), today.isoformat()) == 14
    assert _active_shortcut_days((today - timedelta(days=30)).isoformat(), today.isoformat()) == 30


def test_active_shortcut_is_all_when_there_is_no_date_limit():
    assert _active_shortcut_days(None, None) == "all"


def test_active_shortcut_days_none_when_only_one_end_is_set():
    assert _active_shortcut_days("2026-08-01", None) is None


def test_active_shortcut_days_none_when_end_date_is_not_today():
    # A real but non-"shortcut" range shouldn't be misreported as active.
    today = _today()
    assert _active_shortcut_days(
        (today - timedelta(days=7)).isoformat(), (today - timedelta(days=1)).isoformat()
    ) is None


def test_active_shortcut_days_none_for_a_custom_range():
    today = _today()
    assert _active_shortcut_days((today - timedelta(days=5)).isoformat(), today.isoformat()) is None


# ── the last-30-days default ──────────────────────────────────────────────

def test_no_date_params_defaults_to_the_last_30_days():
    today = _today()
    start, end = _date_range_from_args({})
    assert end == today.isoformat()
    assert start == (today - timedelta(days=DEFAULT_RANGE_DAYS)).isoformat()


def test_default_is_unaffected_by_other_filters_in_the_url():
    # species/pod/etc. in the query string don't count as a date choice.
    start, end = _date_range_from_args({"species": "orca"})
    assert (start, end) == _date_range_from_args({})


def test_present_but_empty_date_params_mean_all_time_not_the_default():
    assert _date_range_from_args({"start_date": "", "end_date": ""}) == (None, None)


def test_explicit_dates_pass_through_unchanged():
    assert _date_range_from_args({"start_date": "2026-08-01", "end_date": "2026-08-31"}) == (
        "2026-08-01", "2026-08-31",
    )


def test_one_date_param_present_does_not_trigger_the_default():
    # Choosing only a start date is an explicit choice -- don't also
    # bolt a default end date onto it.
    assert _date_range_from_args({"start_date": "2026-08-01"}) == ("2026-08-01", None)


def test_is_default_range():
    today = _today()
    assert _is_default_range(
        (today - timedelta(days=DEFAULT_RANGE_DAYS)).isoformat(), today.isoformat()
    )
    assert not _is_default_range(None, None)
    assert not _is_default_range((today - timedelta(days=7)).isoformat(), today.isoformat())
