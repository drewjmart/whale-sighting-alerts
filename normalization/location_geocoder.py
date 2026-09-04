"""
Location name -> lat/lon, for sources that report a place name instead of
coordinates (Acartia already gives real lat/lon directly -- this is for
Orca Network-style free text like "Alki Point" or "San Juan Island").

Static lookup table, not a geocoding API call -- these are a fixed, known
set of Salish Sea whale-watching locations, and a wrong guess (mismatching
a substring to the wrong place) is worse than returning "unresolved."
"""

from __future__ import annotations

import math

# (lat, lon) for well-known Salish Sea whale-watching/reporting locations.
# Keys are the canonical lowercase name; ALIASES below maps common
# variant text to a canonical key.
_LOCATIONS: dict[str, tuple[float, float]] = {
    "alki point": (47.5763, -122.4181),
    "emma schmitz overlook": (47.5651, -122.4131),
    "lincoln park": (47.5299, -122.4133),
    "constellation park": (47.5605, -122.4147),  # includes "Whale Tail Park" -- same landmark
    "discovery park": (47.6598, -122.4147),
    "duwamish head": (47.5836, -122.3865),
    "elliott bay": (47.6062, -122.3599),
    "edmonds": (47.8107, -122.3826),
    "point robinson": (47.3887, -122.3739),
    "point defiance": (47.3054, -122.5150),
    "whidbey island": (48.2223, -122.6415),
    "admiralty inlet": (48.1500, -122.7000),
    "possession point": (47.9106, -122.3667),
    "san juan island": (48.5343, -123.0885),
    "lime kiln point": (48.5157, -123.1522),
    "friday harbor": (48.5354, -123.0161),
    "haro strait": (48.5500, -123.2000),
    "boundary pass": (48.7167, -123.0000),
    "rosario strait": (48.6167, -122.7500),
    "deception pass": (48.4098, -122.6440),
    "orcas island": (48.6926, -122.9426),
    "pilot point": (47.9058, -122.4550),
}

# Common alias text -> canonical key. Substring-matched, longest alias
# checked first so e.g. "lime kiln point" wins over a looser "san juan
# island" match if both happen to appear in the same string.
_ALIASES: dict[str, str] = {
    "whale tail park": "constellation park",
    "west seattle": "alki point",  # closest of our named viewpoints; imprecise, documented
    "elliot bay": "elliott bay",  # common misspelling
}


def geocode_location(location_text: str | None) -> tuple[float, float] | None:
    """Best-effort lat/lon for a free-text location name. Returns None
    (not a guess) if nothing in the table matches."""
    if not location_text:
        return None

    text = location_text.strip().lower()

    if text in _LOCATIONS:
        return _LOCATIONS[text]
    if text in _ALIASES:
        return _LOCATIONS[_ALIASES[text]]

    # Substring match, longest known name/alias first so specific beats general.
    candidates = list(_LOCATIONS.keys()) + list(_ALIASES.keys())
    for name in sorted(candidates, key=len, reverse=True):
        if name in text:
            canonical = _ALIASES.get(name, name)
            return _LOCATIONS[canonical]

    return None


DEFAULT_MAX_NEAREST_MILES = 15.0


def nearest_known_location(lat: float, lon: float, max_distance_miles: float = DEFAULT_MAX_NEAREST_MILES) -> str | None:
    """Reverse of geocode_location(): given real coordinates (Acartia's
    normal case -- it reports lat/lon directly, not a place name), find the
    closest named place from the same table, for human-readable display
    (e.g. the 24h summary on the dashboard home page).

    Returns None beyond max_distance_miles rather than reporting a place
    that's actually nowhere near the sighting -- same "explicit unresolved
    bucket over a wrong guess" principle used everywhere else in this
    project (pod resolution, geocode_location itself).
    """
    best_name, best_distance = None, None
    for name, (place_lat, place_lon) in _LOCATIONS.items():
        distance = _haversine_miles(lat, lon, place_lat, place_lon)
        if best_distance is None or distance < best_distance:
            best_name, best_distance = name, distance

    if best_distance is not None and best_distance <= max_distance_miles:
        return best_name.title()
    return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Small, deliberately duplicated rather than imported from
    # alerts/geo_filter.py -- that package is specifically the live-alert's
    # concern, and this module (normalization) shouldn't depend on it for
    # a five-line formula.
    earth_radius_miles = 3958.8
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, (lat1, lon1, lat2, lon2))
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lon / 2) ** 2
    return 2 * earth_radius_miles * math.asin(math.sqrt(a))
