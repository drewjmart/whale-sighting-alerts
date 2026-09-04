"""
Charts for analysis/correlations.py's findings. Kept separate from
viz/map.py (spatial/species-only) and viz/trends.py (raw counts over
time) -- these are specifically the "does X actually correlate with
sightings" views.
"""

from __future__ import annotations

import sqlite3

import plotly.graph_objects as go

from analysis.correlations import (
    chinook_cpue_trend,
    data_span_summary,
    sightings_by_season_and_year,
    sightings_by_tide_state,
    tide_height_trend,
)
from viz.colors import GRIDLINE, INK_MUTED, INK_PRIMARY, INK_SECONDARY, POD_COLORS, SURFACE

_LAYOUT_DEFAULTS = dict(
    plot_bgcolor=SURFACE,
    paper_bgcolor=SURFACE,
    font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK_PRIMARY, size=13),
    margin=dict(l=50, r=20, t=50, b=40),
)

_TIDE_STATE_COLOR = {"flood": "#2a78d6", "ebb": "#eb6834", "slack": INK_MUTED}
_TIDE_STATE_ORDER = ["flood", "ebb", "slack"]


def tide_state_chart(conn: sqlite3.Connection) -> go.Figure:
    """Sightings per hour of exposure to each tide state -- rate, not raw
    count (see analysis/correlations.py's docstring for why raw counts
    would be misleading here)."""
    result = sightings_by_tide_state(conn)
    fig = go.Figure()

    if not result["counts"]:
        fig.update_layout(title="Sightings by tide state (no data yet)", **_LAYOUT_DEFAULTS)
        return fig

    states = [s for s in _TIDE_STATE_ORDER if s in result["counts"]]
    rates = [result["rates_per_hour"].get(s) for s in states]
    counts = [result["counts"][s] for s in states]

    fig.add_trace(go.Bar(
        x=states,
        y=rates,
        marker_color=[_TIDE_STATE_COLOR[s] for s in states],
        text=[f"{c} sightings" for c in counts],
        textposition="outside",
        hovertemplate="%{x}: %{y:.2f} sightings/hour<br>%{text}<extra></extra>",
    ))
    subtitle = result["note"]
    fig.update_layout(
        title=f"Sightings by tide state (rate, not raw count)<br><sup>{subtitle}</sup>",
        xaxis_title="Tide state",
        yaxis_title="Sightings per hour",
        **_LAYOUT_DEFAULTS,
    )
    fig.update_xaxes(gridcolor=GRIDLINE)
    fig.update_yaxes(gridcolor=GRIDLINE)
    return fig


def tide_height_chart(conn: sqlite3.Connection) -> go.Figure:
    """Tide height over the season -- positioned near tide_state_chart() on
    the dashboard so the two are easy to compare visually, kept as two
    separate single-axis charts rather than one dual-axis chart (a
    dual-axis chart makes two different scales look artificially
    comparable)."""
    df = tide_height_trend(conn)
    fig = go.Figure()

    if df.empty:
        fig.update_layout(title="Tide height over the season (no data yet)", **_LAYOUT_DEFAULTS)
        return fig

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["tide_height_ft"], mode="lines",
        line=dict(color="#2a78d6", width=2),
        hovertemplate="%{x}: %{y:.2f} ft<extra></extra>",
    ))
    fig.update_layout(
        title="Tide height over the season (daily average, MLLW)",
        xaxis_title="Date", yaxis_title="Height (ft)",
        **_LAYOUT_DEFAULTS,
    )
    fig.update_xaxes(gridcolor=GRIDLINE)
    fig.update_yaxes(gridcolor=GRIDLINE)
    return fig


def chinook_cpue_chart(conn: sqlite3.Connection) -> go.Figure:
    """Chinook CPUE (Bonneville daily passage count, used as the proxy)
    over the season -- orca-relevant only, per the feature hierarchy."""
    df = chinook_cpue_trend(conn)
    fig = go.Figure()

    if df.empty:
        fig.update_layout(
            title="Chinook CPUE over the season (no data yet -- orca sightings only)",
            **_LAYOUT_DEFAULTS,
        )
        return fig

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["chinook_cpue"], mode="lines",
        line=dict(color="#eb6834", width=2),
        hovertemplate="%{x}: %{y:.0f} Chinook<extra></extra>",
    ))
    fig.update_layout(
        title="Chinook CPUE over the season <sup>(Bonneville Dam daily passage count -- orca-relevant only)</sup>",
        xaxis_title="Date", yaxis_title="Daily Chinook count",
        **_LAYOUT_DEFAULTS,
    )
    fig.update_xaxes(gridcolor=GRIDLINE)
    fig.update_yaxes(gridcolor=GRIDLINE)
    return fig


def seasonal_chart(conn: sqlite3.Connection) -> go.Figure:
    """Cross-year seasonal pattern -- does sighting timing repeat year to
    year? A single season of data cannot show that; the chart says so
    directly in its title, computed live from the database (see
    data_span_summary), not hardcoded -- it stops saying "preliminary"
    on its own once a second year of data exists."""
    pivot, span = sightings_by_season_and_year(conn)
    fig = go.Figure()

    if pivot.empty:
        fig.update_layout(title="Sightings by season, by year (no data yet)", **_LAYOUT_DEFAULTS)
        return fig

    palette = list(POD_COLORS.values())
    for i, year in enumerate(pivot.columns):
        fig.add_trace(go.Bar(
            x=pivot.index, y=pivot[year], name=str(year),
            marker_color=palette[i % len(palette)],
        ))

    if span["is_single_season"]:
        title = (
            f"Sightings by season, by year "
            f"<br><sup>PRELIMINARY: only {span['n_years']} year of data "
            f"({span['min_date']} to {span['max_date']}) -- this is one season's shape, "
            f"not a confirmed year-over-year pattern. Will stop saying this once a second "
            f"year of data exists.</sup>"
        )
    else:
        title = f"Sightings by season, by year <br><sup>{span['n_years']} years of data</sup>"

    fig.update_layout(
        title=title,
        xaxis_title="Season", yaxis_title="Sighting count",
        barmode="group",
        **_LAYOUT_DEFAULTS,
    )
    fig.update_xaxes(gridcolor=GRIDLINE)
    fig.update_yaxes(gridcolor=GRIDLINE)
    return fig
