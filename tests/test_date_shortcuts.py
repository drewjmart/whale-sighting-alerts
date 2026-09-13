"""
Tests for dashboard/app.py's date-range shortcut helpers (2026-09-13):
"Last 7/14/30 days" links shared by /map and /analysis.
"""

from datetime import date, timedelta

from dashboard.app import _active_shortcut_days, _date_shortcut_urls


def test_date_shortcut_urls_preserves_other_params():
    urls = _date_shortcut_urls("/map", {"species": ["orca"], "trust": "trusted"})
    today = date.today()

    assert set(urls.keys()) == {7, 14, 30}
    for days, url in urls.items():
        assert url.startswith("/map?")
        assert f"start_date={(today - timedelta(days=days)).isoformat()}" in url
        assert f"end_date={today.isoformat()}" in url
        assert "species=orca" in url
        assert "trust=trusted" in url


def test_date_shortcut_urls_with_no_other_filters():
    urls = _date_shortcut_urls("/analysis", {})
    assert urls[7].startswith("/analysis?start_date=")


def test_active_shortcut_days_matches_exact_range():
    today = date.today()
    assert _active_shortcut_days((today - timedelta(days=7)).isoformat(), today.isoformat()) == 7
    assert _active_shortcut_days((today - timedelta(days=14)).isoformat(), today.isoformat()) == 14
    assert _active_shortcut_days((today - timedelta(days=30)).isoformat(), today.isoformat()) == 30


def test_active_shortcut_days_none_when_no_range_set():
    assert _active_shortcut_days(None, None) is None
    assert _active_shortcut_days("2026-08-01", None) is None


def test_active_shortcut_days_none_when_end_date_is_not_today():
    # A real but non-"shortcut" range shouldn't be misreported as active.
    today = date.today()
    assert _active_shortcut_days(
        (today - timedelta(days=7)).isoformat(), (today - timedelta(days=1)).isoformat()
    ) is None


def test_active_shortcut_days_none_for_a_custom_range():
    today = date.today()
    assert _active_shortcut_days((today - timedelta(days=5)).isoformat(), today.isoformat()) is None
