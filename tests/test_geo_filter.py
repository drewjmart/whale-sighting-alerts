"""
Unit tests for alerts/geo_filter.py, including boundary cases per the
acceptance criteria ("confirm it correctly includes/excludes boundary cases").

Boundary points are generated with an independent destination-point
formula (direct geodesic problem), NOT by reusing geo_filter's own
haversine implementation -- so a bug in that implementation can't also
be baked into the test that's supposed to catch it.
"""

import math

from alerts.geo_filter import (
    DEFAULT_CENTER_LAT,
    DEFAULT_CENTER_LON,
    distance_from_center_miles,
    is_within_alert_radius,
)

EARTH_RADIUS_MILES = 3958.8


def _destination_point(lat, lon, bearing_deg, distance_miles):
    """Independent implementation of the direct geodesic problem: given a
    start point, bearing, and distance, compute the destination point."""
    lat1, lon1, bearing = map(math.radians, (lat, lon, bearing_deg))
    d_over_r = distance_miles / EARTH_RADIUS_MILES

    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_over_r) + math.cos(lat1) * math.sin(d_over_r) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(d_over_r) * math.cos(lat1),
        math.cos(d_over_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def test_center_point_itself_is_within_radius():
    assert is_within_alert_radius(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON) is True


def test_known_real_points():
    # Alki Point is genuinely close to the West Seattle center point.
    assert is_within_alert_radius(47.5763, -122.4181) is True
    # San Juan Island is ~60mi away -- clearly outside an 8mi radius.
    assert is_within_alert_radius(48.5343, -123.0885) is False


def test_boundary_just_inside_radius_is_included():
    # A point 0.1mi inside the configured radius, due north of center.
    lat, lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0, 7.9)
    assert is_within_alert_radius(lat, lon) is True


def test_boundary_just_outside_radius_is_excluded():
    # A point 0.1mi outside the configured radius, due north of center.
    lat, lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0, 8.1)
    assert is_within_alert_radius(lat, lon) is False


def test_boundary_exactly_at_radius_is_inclusive():
    # Exactly at the radius distance -- documented as inclusive.
    lat, lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 45, 8.0)
    distance = distance_from_center_miles(lat, lon)
    assert distance == 8.0 or abs(distance - 8.0) < 0.01  # geodesic formula float tolerance
    assert is_within_alert_radius(lat, lon) is True


def test_boundary_holds_in_every_direction_not_just_north():
    # Same 7.9mi-inside / 8.1mi-outside check, but at several bearings --
    # a bug in the lon/lat delta math could pass a single-bearing test by
    # coincidence.
    for bearing in (0, 90, 180, 270, 45, 225):
        inside_lat, inside_lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, bearing, 7.9)
        outside_lat, outside_lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, bearing, 8.1)
        assert is_within_alert_radius(inside_lat, inside_lon) is True, f"bearing {bearing}"
        assert is_within_alert_radius(outside_lat, outside_lon) is False, f"bearing {bearing}"


def test_config_env_override(monkeypatch):
    # Radius is config-driven, not hardcoded -- confirm env vars actually change behavior.
    monkeypatch.setenv("ALERT_RADIUS_MILES", "1")
    # San Juan Island, clearly outside a 1mi radius too, but this specifically
    # confirms the env var is read at call time, not baked in at import time.
    assert is_within_alert_radius(48.5343, -123.0885) is False

    # A point 0.5mi from the default center should now pass...
    lat, lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0, 0.5)
    assert is_within_alert_radius(lat, lon) is True
    # ...but 1.5mi away should now fail, where it would have passed under the 8mi default.
    lat, lon = _destination_point(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0, 1.5)
    assert is_within_alert_radius(lat, lon) is False
