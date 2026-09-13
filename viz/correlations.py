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
    tide_height_vs_sightings,
)
from viz.colors import chart_chrome, pod_colors

_TIDE_STATE_ORDER = ["flood", "ebb", "slack"]


def _layout_defaults(theme: str) -> dict:
    chrome = chart_chrome(theme)
    return dict(
        plot_bgcolor=chrome["surface"],
        paper_bgcolor=chrome["surface"],
        font=dict(
            family="system-ui, -apple-system, 'Segoe UI', sans-serif",
            color=chrome["ink_primary"], size=13,
        ),
        margin=dict(l=50, r=20, t=50, b=40),
        # Plotly's modebar (camera/zoom icons) defaults to light styling
        # regardless of the chart's own colors -- without this it'd stay a
        # bright rectangle floating over a dark chart.
        modebar=dict(bgcolor=chrome["surface"], color=chrome["ink_muted"], activecolor=chrome["ink_primary"]),
    )


def _tide_state_colors(theme: str) -> dict[str, str]:
    pods = pod_colors(theme)
    return {"flood": pods["J"], "ebb": pods["K"], "slack": chart_chrome(theme)["ink_muted"]}


def tide_state_chart(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: list[str] | None = None,
    theme: str = "light",
) -> go.Figure:
    """Sightings per hour of exposure to each tide state -- rate, not raw
    count (see analysis/correlations.py's docstring for why raw counts
    would be misleading here)."""
    result = sightings_by_tide_state(conn, start_date=start_date, end_date=end_date, species=species)
    fig = go.Figure()
    layout_defaults = _layout_defaults(theme)
    gridline = chart_chrome(theme)["gridline"]

    if not result["counts"]:
        fig.update_layout(title="Sightings by tide state (no data yet)", **layout_defaults)
        return fig

    tide_colors = _tide_state_colors(theme)
    states = [s for s in _TIDE_STATE_ORDER if s in result["counts"]]
    rates = [result["rates_per_hour"].get(s) for s in states]
    counts = [result["counts"][s] for s in states]

    fig.add_trace(go.Bar(
        x=states,
        y=rates,
        marker_color=[tide_colors[s] for s in states],
        text=[f"{c} sightings" for c in counts],
        textposition="outside",
        hovertemplate="%{x}: %{y:.2f} sightings/hour<br>%{text}<extra></extra>",
    ))
    subtitle = result["note"]
    fig.update_layout(
        title=f"Sightings by tide state (rate, not raw count)<br><sup>{subtitle}</sup>",
        xaxis_title="Tide state",
        yaxis_title="Sightings per hour",
        **layout_defaults,
    )
    fig.update_xaxes(gridcolor=gridline)
    fig.update_yaxes(gridcolor=gridline)
    return fig


def _min_max_normalize(series):
    """Scale a series to 0-100 over its own [min, max] -- used instead of
    "% of max" (chinook_cpue_chart's approach) for tide height specifically,
    since tide height can be negative (MLLW datum) and "% of max" distorts
    once negative values are in play. A flat/constant series (max == min)
    normalizes to a flat 50 rather than dividing by zero."""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return series * 0 + 50
    return (series - lo) / (hi - lo) * 100


def tide_height_chart(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: list[str] | None = None,
    theme: str = "light",
) -> go.Figure:
    """Tide height alongside sighting counts, over the season -- so it's
    visually clear whether sighting frequency tracks tide height (2026-09-08
    feedback: the original version plotted only the tide curve with nothing
    to compare it against, which wasn't the point of having it next to the
    tide-state chart).

    Same normalize-to-a-shared-axis approach as chinook_cpue_chart, and for
    the same reason -- a literal dual-axis chart lets you make any two
    series "look correlated" by choosing where each axis starts/ends, which
    defeats the purpose when the entire point is judging correlation by
    eye. Min-max normalized (not "% of max") specifically because tide
    height can be negative; raw values are still on hover.
    """
    df = tide_height_vs_sightings(conn, start_date=start_date, end_date=end_date, species=species)
    fig = go.Figure()
    layout_defaults = _layout_defaults(theme)
    chrome = chart_chrome(theme)
    pods = pod_colors(theme)

    if df.empty:
        fig.update_layout(title="Tide height vs. sightings (no data yet)", **layout_defaults)
        return fig

    tide_norm = _min_max_normalize(df["tide_height_ft"])
    count_norm = _min_max_normalize(df["sighting_count"])

    fig.add_trace(go.Scatter(
        x=df["date"], y=tide_norm, mode="lines", name="Tide height",
        line=dict(color=pods["J"], width=2),
        customdata=df["tide_height_ft"],
        hovertemplate="%{x}: %{customdata:.2f} ft<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=count_norm, mode="lines", name="Sightings",
        line=dict(color=pods["K"], width=2),
        customdata=df["sighting_count"],
        hovertemplate="%{x}: %{customdata:.0f} sighting(s)<extra></extra>",
    ))
    legend_bg = "rgba(26,26,25,0.8)" if theme == "dark" else "rgba(252,252,251,0.8)"
    layout = dict(layout_defaults, margin=dict(l=50, r=20, t=90, b=40))  # taller top margin -- two-line title
    fig.update_layout(
        title=(
            "Tide height vs. sightings, over the season "
            "<br><sup>Both scaled to their own 0-100 range (not raw units) so they share one axis -- "
            "hover for real values (tide height in ft, MLLW).</sup>"
        ),
        xaxis_title="Date", yaxis_title="Scaled 0-100 (own range)",
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99, bgcolor=legend_bg),
        **layout,
    )
    fig.update_xaxes(gridcolor=chrome["gridline"])
    fig.update_yaxes(gridcolor=chrome["gridline"])
    return fig


def chinook_cpue_chart(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: list[str] | None = None,
    theme: str = "light",
) -> go.Figure:
    """Daily Chinook salmon passage count at Bonneville Dam, used as a
    salmon-activity proxy, alongside daily orca sighting counts -- so it's
    visually clear whether sighting frequency tracks salmon abundance.

    Labeling (2026-09-08 feedback): the underlying data (and the
    `chinook_cpue` field/function names throughout this codebase) uses
    "CPUE" -- Catch Per Unit Effort, a fisheries term -- but what's
    actually stored is a raw daily fish count at Bonneville Dam, not a
    catch-per-effort figure. Every user-facing label here says "Chinook
    salmon count/activity" instead; internal names are unchanged (a
    field/column rename is a separate, riskier change than fixing what's
    actually shown on screen).

    Deliberately NOT a dual-axis chart: two y-scales on one plot is the
    #1 chart-design mistake precisely because it lets you make any two
    unrelated series "look correlated" by choosing where each axis
    starts/ends -- exactly the failure mode to avoid when the entire
    point of the chart is judging correlation by eye. Both series are
    instead normalized to % of their own max and share one axis; raw
    values are still available on hover. No correlation coefficient is
    computed -- this is a visual comparison only, per the ask.

    `species` is accepted for interface consistency with the other
    /analysis charts (so the page's filter form can call every chart the
    same way) but has no effect -- this chart is always orca vs. salmon
    count. A note says so explicitly rather than silently ignoring a
    filter the viewer just set, which would look like a bug.
    """
    df = chinook_cpue_vs_orca_sightings(conn, start_date=start_date, end_date=end_date)
    fig = go.Figure()
    layout_defaults = _layout_defaults(theme)
    chrome = chart_chrome(theme)
    pods = pod_colors(theme)
    species_filter_note = (
        " Note: this chart is always orca-only regardless of the species filter above -- "
        "salmon activity has no meaning for other species."
        if species and species != ["orca"]
        else ""
    )

    if df.empty:
        fig.update_layout(
            title="Chinook salmon activity vs. orca sightings (no data yet)",
            **layout_defaults,
        )
        return fig

    cpue_max = df["chinook_cpue"].max()
    count_max = df["sighting_count"].max()
    cpue_norm = (df["chinook_cpue"] / cpue_max * 100) if cpue_max else df["chinook_cpue"]
    count_norm = (df["sighting_count"] / count_max * 100) if count_max else df["sighting_count"]

    fig.add_trace(go.Scatter(
        x=df["date"], y=cpue_norm, mode="lines", name="Chinook salmon count",
        line=dict(color=pods["K"], width=2),
        customdata=df["chinook_cpue"],
        hovertemplate="%{x}: %{customdata:.0f} Chinook (Bonneville Dam)<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=count_norm, mode="lines", name="Orca sightings",
        line=dict(color=pods["J"], width=2),
        customdata=df["sighting_count"],
        hovertemplate="%{x}: %{customdata:.0f} sighting(s)<extra></extra>",
    ))
    legend_bg = "rgba(26,26,25,0.8)" if theme == "dark" else "rgba(252,252,251,0.8)"
    layout = dict(layout_defaults, margin=dict(l=50, r=20, t=90, b=40))  # taller top margin -- two-line title
    fig.update_layout(
        title=(
            "Chinook salmon activity vs. orca sightings, over the season "
            "<br><sup>Both normalized to % of their own max (not raw units) so they share one axis -- "
            "hover for real values. Daily Chinook count at Bonneville Dam used as a salmon-activity proxy "
            f"(not a true catch-per-effort figure); orca-relevant only, per the feature hierarchy."
            f"{species_filter_note}</sup>"
        ),
        xaxis_title="Date", yaxis_title="% of season max",
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99, bgcolor=legend_bg),
        **layout,
    )
    fig.update_xaxes(gridcolor=chrome["gridline"])
    fig.update_yaxes(gridcolor=chrome["gridline"])
    return fig


def seasonal_chart(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: list[str] | None = None,
    theme: str = "light",
) -> go.Figure:
    """Cross-year seasonal pattern -- does sighting timing repeat year to
    year? A single season of data cannot show that; the chart says so
    directly in its title, computed live from the database (see
    data_span_summary), not hardcoded -- it stops saying "preliminary"
    on its own once a second year of data exists."""
    pivot, span = sightings_by_season_and_year(conn, start_date=start_date, end_date=end_date, species=species)
    fig = go.Figure()
    layout_defaults = _layout_defaults(theme)
    gridline = chart_chrome(theme)["gridline"]

    if pivot.empty:
        fig.update_layout(title="Sightings by season, by year (no data yet)", **layout_defaults)
        return fig

    palette = list(pod_colors(theme).values())
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
        **layout_defaults,
    )
    fig.update_xaxes(gridcolor=gridline)
    fig.update_yaxes(gridcolor=gridline)
    return fig
