"""
Trend charts over time, built directly on top of analysis/pivots.py's
pivot tables (species x month, pod x month) rather than re-querying --
one source of truth for the counts shown in both the pivot tables and
these charts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import plotly.graph_objects as go

from analysis.pivots import pod_by_month, species_by_month


def species_trend_chart(conn: sqlite3.Connection) -> go.Figure:
    pivot = species_by_month(conn)
    fig = go.Figure()
    if pivot.empty:
        fig.update_layout(title="Sightings by species over time (no data yet)")
        return fig

    for species in pivot.index:
        fig.add_trace(go.Scatter(x=pivot.columns, y=pivot.loc[species], mode="lines+markers", name=species))

    fig.update_layout(
        title="Sightings by species over time",
        xaxis_title="Month",
        yaxis_title="Sighting count",
        legend_title="Species",
    )
    return fig


def pod_trend_chart(conn: sqlite3.Connection) -> go.Figure:
    pivot = pod_by_month(conn)
    fig = go.Figure()
    if pivot.empty:
        fig.update_layout(title="Orca sightings by pod over time (no data yet)")
        return fig

    for pod in pivot.index:
        fig.add_trace(go.Scatter(x=pivot.columns, y=pivot.loc[pod], mode="lines+markers", name=pod))

    fig.update_layout(
        title="Orca sightings by pod over time",
        xaxis_title="Month",
        yaxis_title="Sighting count",
        legend_title="Pod",
    )
    return fig


def save_chart(fig: go.Figure, out_path: Path | str) -> Path:
    out_path = Path(out_path)
    fig.write_html(str(out_path))
    return out_path


if __name__ == "__main__":
    from storage.db import DEFAULT_DB_PATH, get_connection

    conn = get_connection(DEFAULT_DB_PATH)
    out1 = save_chart(species_trend_chart(conn), "trends_species.html")
    out2 = save_chart(pod_trend_chart(conn), "trends_pod.html")
    print(f"Wrote {out1} and {out2}")
