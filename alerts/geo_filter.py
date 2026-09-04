"""
Hard boolean gate for push notifications: is this sighting close enough to
West Seattle to be worth an alert?

Deliberately separate from analysis/location_query.py (see spec §1a) --
that's an interactive "show me this region" parameter with no restriction;
this is a fixed "should this notify me" gate. Same underlying coordinate
math (haversine distance), different purpose, different code path, and
this one uses exact haversine rather than location_query's cheaper bbox
approximation, since a boundary case here has a real consequence (an alert
either fires or it doesn't).

Config-driven, not hardcoded: center point and radius both come from
environment variables (see .env.example), defaulting to West Seattle /
~8 miles (covering Alki Point, Emma Schmitz Overlook, Lincoln Park) --
tune ALERT_RADIUS_MILES once live without touching code.
"""

from __future__ import annotations

import math
import os

EARTH_RADIUS_MILES = 3958.8

# Same West Seattle reference point whale_alert.py already uses for its
# sunrise/sunset calculation (SEATTLE LocationInfo, 47.5615, -122.3866).
DEFAULT_CENTER_LAT = 47.5615
DEFAULT_CENTER_LON = -122.3866
DEFAULT_RADIUS_MILES = 8.0


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, (lat1, lon1, lat2, lon2))
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _env_float(name: str, default: float) -> float:
    # os.environ.get(name, default) only falls through to `default` when
    # the var is entirely UNSET. .env.example (and a real .env copied from
    # it) ships these blank -- "ALERT_CENTER_LAT=" -- which is SET to "",
    # not unset, so .get() returned "" and float("") crashed. Found this
    # once .env actually started getting loaded (see run_backfill.py).
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


def get_alert_center() -> tuple[float, float]:
    lat = _env_float("ALERT_CENTER_LAT", DEFAULT_CENTER_LAT)
    lon = _env_float("ALERT_CENTER_LON", DEFAULT_CENTER_LON)
    return lat, lon


def get_alert_radius_miles() -> float:
    return _env_float("ALERT_RADIUS_MILES", DEFAULT_RADIUS_MILES)


def is_within_alert_radius(lat: float, lon: float) -> bool:
    """The hard gate: True if (lat, lon) is within the configured radius of
    the configured center. Inclusive at the exact boundary distance."""
    center_lat, center_lon = get_alert_center()
    radius = get_alert_radius_miles()
    distance = _haversine_miles(center_lat, center_lon, lat, lon)
    return distance <= radius


def distance_from_center_miles(lat: float, lon: float) -> float:
    """Exposed separately for logging/debugging -- how far a sighting was
    from the alert center, regardless of whether it passed the gate."""
    center_lat, center_lon = get_alert_center()
    return _haversine_miles(center_lat, center_lon, lat, lon)


if __name__ == "__main__":
    center = get_alert_center()
    radius = get_alert_radius_miles()
    print(f"Alert center: {center}, radius: {radius}mi")

    test_points = [
        ("Alki Point", 47.5763, -122.4181),
        ("San Juan Island", 48.5343, -123.0885),
    ]
    for name, lat, lon in test_points:
        dist = distance_from_center_miles(lat, lon)
        within = is_within_alert_radius(lat, lon)
        print(f"  {name}: {dist:.1f}mi -> {'ALERT' if within else 'suppressed'}")
