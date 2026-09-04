"""
NOAA CO-OPS tide predictions.

Confirmed live (2026-08-27): keyless, public REST API. Station 9447130 is
Seattle -- the nearest reliable CO-OPS reference station to West Seattle's
shore viewpoints (Alki/Emma Schmitz/Lincoln Park), and to the Puget Sound
sightings generally.

Tide state (flood/ebb/slack) is a secondary modifier applied across ALL
species per the README feature hierarchy (unlike Chinook CPUE, which is
orca-only) -- tide-driven current and prey behavior affects foraging
opportunity broadly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
SEATTLE_STATION = "9447130"
REQUEST_TIMEOUT = 20
SLACK_WINDOW_MINUTES = 30  # within this of a high/low extreme, call it "slack" rather than flood/ebb


class TideClientError(Exception):
    pass


@dataclass
class TideEvent:
    at: datetime          # naive local time (station's local standard/daylight time, per NOAA's lst_ldt)
    height_ft: float
    kind: str              # "H" or "L"


def fetch_tide_predictions(
    begin: datetime, end: datetime, station: str = SEATTLE_STATION
) -> list[TideEvent]:
    """Fetch high/low tide predictions for a date range. Confirmed live
    against NOAA CO-OPS; date range should not exceed what a single
    `datagetter` call supports (a few months is safe)."""
    params = {
        "product": "predictions",
        "application": "whale_sighting_tracker",
        "begin_date": begin.strftime("%Y%m%d %H:%M"),
        "end_date": end.strftime("%Y%m%d %H:%M"),
        "datum": "MLLW",
        "station": station,
        "time_zone": "lst_ldt",
        "units": "english",
        "interval": "hilo",
        "format": "json",
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TideClientError(f"NOAA CO-OPS request failed: {exc}") from exc

    if "error" in data:
        raise TideClientError(f"NOAA CO-OPS returned an error: {data['error'].get('message')}")

    events: list[TideEvent] = []
    for p in data.get("predictions", []):
        try:
            events.append(
                TideEvent(
                    at=datetime.strptime(p["t"], "%Y-%m-%d %H:%M"),
                    height_ft=float(p["v"]),
                    kind=p["type"],
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("skipped unparseable tide prediction %r: %s", p, exc)

    return events


def compute_tide_state(at: datetime, events: list[TideEvent]) -> tuple[str | None, float | None]:
    """Given a timestamp and a list of surrounding high/low events (must
    bracket `at` -- pass a wide enough window from fetch_tide_predictions),
    return (tide_state, interpolated_height_ft).

    tide_state is 'flood' (rising, between a Low and the next High), 'ebb'
    (falling, between a High and the next Low), or 'slack' (within
    SLACK_WINDOW_MINUTES of a high/low extreme). Returns (None, None) if
    `at` isn't bracketed by events on both sides.
    """
    before = [e for e in events if e.at <= at]
    after = [e for e in events if e.at >= at]
    if not before or not after:
        return None, None

    prev_event = max(before, key=lambda e: e.at)
    next_event = min(after, key=lambda e: e.at)

    if prev_event.at == next_event.at:
        # Sitting exactly on an event.
        return "slack", prev_event.height_ft

    minutes_to_nearest_extreme = min(
        abs((at - prev_event.at).total_seconds()) / 60,
        abs((next_event.at - at).total_seconds()) / 60,
    )
    if minutes_to_nearest_extreme <= SLACK_WINDOW_MINUTES:
        nearer = prev_event if (at - prev_event.at) <= (next_event.at - at) else next_event
        return "slack", nearer.height_ft

    # Linear interpolation between the two bracketing extremes -- a
    # reasonable approximation for a secondary modifier feature, not a
    # tide-curve model.
    span = (next_event.at - prev_event.at).total_seconds()
    fraction = (at - prev_event.at).total_seconds() / span
    height = prev_event.height_ft + fraction * (next_event.height_ft - prev_event.height_ft)

    state = "flood" if prev_event.kind == "L" else "ebb"
    return state, round(height, 3)


def tide_state_exposure_minutes(events: list[TideEvent]) -> dict[str, float]:
    """Total real minutes spent in each tide state across a span of
    events -- needed to compare sighting counts *by rate*, not raw count.

    'slack' is a fixed +/-30min band around every extreme (SLACK_WINDOW_MINUTES),
    while 'flood'/'ebb' are the multi-hour legs between extremes -- so slack's
    time window is mechanically much smaller. A raw sighting-count comparison
    would always show fewer slack sightings for that reason alone, regardless
    of whether whales actually behave differently at slack tide. This computes
    the real, per-leg exposure so a rate (sightings per hour of that state)
    can be computed instead.
    """
    events = sorted(events, key=lambda e: e.at)
    totals = {"flood": 0.0, "ebb": 0.0, "slack": 0.0}

    for prev_event, next_event in zip(events, events[1:]):
        leg_minutes = (next_event.at - prev_event.at).total_seconds() / 60
        slack_minutes = min(SLACK_WINDOW_MINUTES, leg_minutes / 2) * 2
        remaining = max(0.0, leg_minutes - slack_minutes)

        totals["slack"] += slack_minutes
        if prev_event.kind == "L":
            totals["flood"] += remaining
        else:
            totals["ebb"] += remaining

    return totals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    now = datetime.now()
    events = fetch_tide_predictions(now - timedelta(days=1), now + timedelta(days=1))
    print(f"Fetched {len(events)} tide event(s) around Seattle station {SEATTLE_STATION}.")
    for e in events[:6]:
        print(f"  {e.at}  {e.kind}  {e.height_ft} ft")

    state, height = compute_tide_state(now, events)
    print(f"Right now: tide_state={state}  height={height} ft")
