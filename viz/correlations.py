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
    chinook_cpue_vs_orca_sightings,
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
    over the season, alongside daily orca sighting counts -- so it's
    visually clear whether sighting frequency tracks salmon abundance.

    Deliberately NOT a dual-axis chart: two y-scales on one plot is the
    #1 chart-design mistake precisely because it lets you make any two
    unrelated series "look correlated" by choosing where each axis
    starts/ends -- exactly the failure mode to avoid when the entire
    point of the chart is judging correlation by eye. Both series are
    instead normalized to % of their own max and share one axis; raw
    values are still available on hover. No correlation coefficient is
    computed -- this is a visual comparison only, per the ask.
    """
    df = chinook_cpue_vs_orca_sightings(conn)
    fig = go.Figure()

    if df.empty:
        fig.update_layout(
            title="Chinook CPUE vs. orca sightings (no data yet)",
            **_LAYOUT_DEFAULTS,
        )
        return fig

    cpue_max = df["chinook_cpue"].max()
    count_max = df["sighting_count"].max()
    cpue_norm = (df["chinook_cpue"] / cpue_max * 100) if cpue_max else df["chinook_cpue"]
    count_norm = (df["sighting_count"] / count_max * 100) if count_max else df["sighting_count"]

    fig.add_trace(go.Scatter(
        x=df["date"], y=cpue_norm, mode="lines", name="Chinook CPUE",
        line=dict(color="#eb6834", width=2),
        customdata=df["chinook_cpue"],
        hovertemplate="%{x}: %{customdata:.0f} Chinook<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=count_norm, mode="lines", name="Orca sightings",
        line=dict(color="#2a78d6", width=2),
        customdata=df["sighting_count"],
        hovertemplate="%{x}: %{customdata:.0f} sighting(s)<extra></extra>",
    ))
    layout = dict(_LAYOUT_DEFAULTS, margin=dict(l=50, r=20, t=90, b=40))  # taller top margin -- two-line title
    fig.update_layout(
        title=(
            "Chinook CPUE vs. orca sightings, over the season "
            "<br><sup>Both normalized to % of their own max (not raw units) so they share one axis -- "
            "hover for real values. Bonneville Dam daily passage count used as the CPUE proxy; "
            "orca-relevant only, per the feature hierarchy.</sup>"
        ),
        xaxis_title="Date", yaxis_title="% of season max",
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99, bgcolor="rgba(252,252,251,0.8)"),
        **layout,
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
