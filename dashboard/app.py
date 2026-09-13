"""
Local dashboard -- Flask app wrapping the map, pivot tables, and region
query in a browsable web UI.

Build and test entirely via `flask run` / localhost. No deployment in
this PR -- see README §Phase 2 for the (separate, later) Render step.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request

# Found while wiring up the Acartia token: nothing in this codebase loaded
# .env anywhere, so ALERT_CENTER_LAT/LON/RADIUS_MILES (alerts/geo_filter.py)
# would silently fall back to defaults even when set. Load it here since
# this is an entry point (python -m dashboard.app / flask run).
load_dotenv(Path(__file__).parent.parent / ".env")

from analysis.location_query import known_regions, query_region
from analysis.pivots import (
    add_totals,
    days_since_last_sighting,
    location_by_species,
    most_active_location,
    most_active_pod_this_season,
    pod_by_month,
    recent_24h_summary,
    season_total_with_change,
    species_by_month,
)
from normalization.pod_resolver import (
    POD_DISPLAY_NAMES,
    SPECIES_DISPLAY_NAMES,
    VALID_SPECIES,
    pod_code_display,
    species_display_name,
)
from storage.db import DEFAULT_DB_PATH, get_connection
from viz.correlations import chinook_cpue_chart, seasonal_chart, tide_height_chart, tide_state_chart
from viz.map import POD_ROWS, build_map

app = Flask(__name__)

# Friendly display names (2026-09-08) everywhere a species/pod code would
# otherwise reach the page verbatim -- {{ s | friendly_species }} instead
# of every template inventing its own title-casing, and one place to fix
# if VALID_SPECIES ever grows.
app.jinja_env.filters["friendly_species"] = species_display_name
app.jinja_env.filters["friendly_pod"] = pod_code_display


def _conn():
    # One short-lived connection per request -- simple and correct for a
    # local, single-user dashboard; not meant to scale past that.
    return get_connection(DEFAULT_DB_PATH)


def _current_theme() -> str:
    """Dark mode (2026-09-08) is an explicit, persisted choice -- not an
    automatic prefers-color-scheme flip -- so page chrome, every chart,
    and the map basemap all agree on the same theme at request time
    without needing a client-side re-render for the charts/map (which are
    server-rendered HTML, not live JS components)."""
    theme = request.cookies.get("theme", "light")
    return theme if theme in ("light", "dark") else "light"


@app.context_processor
def inject_theme():
    # Makes {{ theme }} available in every template (the nav toggle button,
    # and base.html's <html data-theme="..."> stamp) without every view
    # function having to pass it explicitly.
    return {"theme": _current_theme()}


@app.route("/theme/toggle", methods=["POST"])
def toggle_theme():
    """Flips the theme cookie and redirects back to whatever page the
    toggle was clicked from. No JS re-render needed -- charts and the map
    are re-rendered server-side on the next request anyway, from the same
    cookie every view function reads via _current_theme()."""
    new_theme = "light" if _current_theme() == "dark" else "dark"
    response = redirect(request.referrer or "/")
    response.set_cookie("theme", new_theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@app.route("/")
def index():
    """Deliberately minimal (2026-09-08): just the 24h summary and the KPI
    panes -- the full species/location breakdowns and region browsing that
    used to live here moved to their own dedicated pages (/pivots and
    /map respectively) rather than duplicating them in two places."""
    conn = _conn()
    try:
        recent = recent_24h_summary(conn)
        kpis = dict(
            season=season_total_with_change(conn),
            active_location=most_active_location(conn),
            days_since=days_since_last_sighting(conn),
            active_pod=most_active_pod_this_season(conn),
        )
    finally:
        conn.close()
    return render_template("index.html", recent=recent, kpis=kpis)


_DATE_SHORTCUT_DAYS = (7, 14, 30)


def _date_shortcut_urls(base_path: str, preserved_params: dict) -> dict[int, str]:
    """'Last N days' shortcut links for a filter form (2026-09-13) -- one
    helper shared by /map and /analysis so both pages' shortcuts are built
    the same way, rather than each view re-deriving today's date and
    re-encoding params. `preserved_params` carries every OTHER currently
    set filter (species, pod, trust, ...) so clicking a shortcut narrows
    the date range without silently discarding filters set elsewhere on
    the same form."""
    today = date.today()
    urls = {}
    for days in _DATE_SHORTCUT_DAYS:
        params = dict(preserved_params)
        params["start_date"] = (today - timedelta(days=days)).isoformat()
        params["end_date"] = today.isoformat()
        urls[days] = f"{base_path}?{urlencode(params, doseq=True)}"
    return urls


def _active_shortcut_days(start_date: str | None, end_date: str | None) -> int | None:
    """Which shortcut (if any) exactly matches the current start/end date
    -- purely cosmetic, to highlight the active one; returns None if the
    current range doesn't match any shortcut (including no range at all)."""
    today = date.today()
    if not start_date or not end_date or end_date != today.isoformat():
        return None
    for days in _DATE_SHORTCUT_DAYS:
        if start_date == (today - timedelta(days=days)).isoformat():
            return days
    return None


def _map_filters_from_request() -> dict:
    return dict(
        start_date=request.args.get("start_date") or None,
        end_date=request.args.get("end_date") or None,
        region=request.args.get("region") or None,
        species=request.args.getlist("species") or None,
        pod=request.args.getlist("pod") or None,
        trust=request.args.get("trust") or "all",
        tracks=request.args.get("tracks") == "1",
    )


@app.route("/map")
def map_view():
    """Filter UI (species/pod checkboxes, date range, trust-level toggle --
    2026-09-08) plus the actual map, which lives in an iframe pointing at
    /map/frame. It's an iframe rather than an inlined fragment because
    folium renders a full standalone <html> document (its own <head> with
    the Leaflet script/CSS tags) -- unlike plotly's to_html(full_html=False)
    fragments on /analysis, that can't be safely embedded inside another
    page's own <html>. Same GET-params-in-the-URL pattern as /analysis:
    shareable/bookmarkable, no JS required to apply a filter."""
    filters = _map_filters_from_request()

    frame_params: dict = {}
    if filters["start_date"]:
        frame_params["start_date"] = filters["start_date"]
    if filters["end_date"]:
        frame_params["end_date"] = filters["end_date"]
    if filters["region"]:
        frame_params["region"] = filters["region"]
    if filters["species"]:
        frame_params["species"] = filters["species"]
    if filters["pod"]:
        frame_params["pod"] = filters["pod"]
    if filters["trust"] != "all":
        frame_params["trust"] = filters["trust"]
    if filters["tracks"]:
        frame_params["tracks"] = "1"

    # frame_params minus the date keys is exactly "every other filter
    # currently set" -- reuse it rather than re-deriving the same thing.
    preserved = {k: v for k, v in frame_params.items() if k not in ("start_date", "end_date")}

    return render_template(
        "map.html",
        frame_query=urlencode(frame_params, doseq=True),
        all_species=sorted(VALID_SPECIES),
        selected_species=filters["species"] or [],
        pod_rows=POD_ROWS,
        selected_pods=filters["pod"] or [],
        start_date=filters["start_date"] or "",
        end_date=filters["end_date"] or "",
        trust=filters["trust"],
        show_tracks=filters["tracks"],
        regions=known_regions(),
        shortcut_urls=_date_shortcut_urls("/map", preserved),
        active_shortcut_days=_active_shortcut_days(filters["start_date"], filters["end_date"]),
    )


@app.route("/map/frame")
def map_frame():
    """The actual folium document -- embedded via iframe by /map, not
    linked to directly (no filter UI or page chrome here on its own)."""
    filters = _map_filters_from_request()

    conn = _conn()
    try:
        fmap = build_map(
            conn,
            start_date=filters["start_date"],
            end_date=filters["end_date"],
            region=filters["region"],
            species=filters["species"],
            pod_codes=filters["pod"],
            trusted_only=filters["trust"] == "trusted",
            theme=_current_theme(),
            show_tracks=filters["tracks"],
        )
    finally:
        conn.close()
    return fmap.get_root().render()


@app.route("/pivots")
def pivots_view():
    conn = _conn()
    try:
        species_month = species_by_month(conn)
        species_counts = {
            species_display_name(species): int(row.sum())
            for species, row in species_month.iterrows()
        }
        # .rename() only touches keys present in the map -- "Total" (the
        # margins row/column added below) passes through unrenamed.
        tables = {
            "Orca sightings by pod x month": add_totals(pod_by_month(conn).rename(index=POD_DISPLAY_NAMES)),
            "Sightings by species x month": add_totals(species_month.rename(index=SPECIES_DISPLAY_NAMES)),
            "Sightings by location x species": add_totals(
                location_by_species(conn).rename(columns=SPECIES_DISPLAY_NAMES)
            ),
        }
    finally:
        conn.close()
    html_tables = {
        title: (df.to_html(classes="pivot-table") if not df.empty else "<p>No data yet.</p>")
        for title, df in tables.items()
    }
    return render_template("pivots.html", tables=html_tables, species_counts=species_counts)


@app.route("/analysis")
def analysis_view():
    """Correlation views -- does sighting frequency actually vary with tide
    state, season, or (orca) salmon abundance. Deliberately separate from
    /map (spatial/species only, per the original design principle).

    Filters (date range + species multi-select, 2026-09-05) are read from
    query params and passed to every chart -- GET params rather than a JS
    form submit, so the filtered view is a shareable/bookmarkable URL and
    works with no JS at all, same pattern as /map's ?region=&start_date=.
    """
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None
    species = request.args.getlist("species") or None

    theme = _current_theme()
    conn = _conn()
    try:
        charts = [
            tide_state_chart(conn, start_date=start_date, end_date=end_date, species=species, theme=theme),
            tide_height_chart(conn, start_date=start_date, end_date=end_date, species=species, theme=theme),
            chinook_cpue_chart(conn, start_date=start_date, end_date=end_date, species=species, theme=theme),
            seasonal_chart(conn, start_date=start_date, end_date=end_date, species=species, theme=theme),
        ]
    finally:
        conn.close()

    chart_html = [
        fig.to_html(full_html=False, include_plotlyjs=("cdn" if i == 0 else False))
        for i, fig in enumerate(charts)
    ]

    preserved = {"species": species} if species else {}

    return render_template(
        "analysis.html",
        chart_html=chart_html,
        all_species=sorted(VALID_SPECIES),
        selected_species=species or [],
        start_date=start_date or "",
        end_date=end_date or "",
        shortcut_urls=_date_shortcut_urls("/analysis", preserved),
        active_shortcut_days=_active_shortcut_days(start_date, end_date),
    )


@app.route("/about")
def about_view():
    """Static explainer page -- what this shows, where the data comes
    from, what each chart means, how to use the filters. No query, no
    conn needed."""
    return render_template("about.html")


@app.route("/region/<region_name>")
def region_view(region_name: str):
    conn = _conn()
    try:
        try:
            rows = query_region(conn, region_name)
        except ValueError:
            abort(404, f"Unknown region {region_name!r}. Known: {', '.join(known_regions())}")
        sightings = [dict(row) for row in rows]
    finally:
        conn.close()
    return render_template("region.html", region=region_name, sightings=sightings)


if __name__ == "__main__":
    # Run as `python -m dashboard.app` from the repo root, NOT
    # `python dashboard/app.py` directly -- confirmed the latter breaks
    # the sibling-package imports above (analysis, storage, viz) since a
    # directly-executed script only gets its own directory on sys.path,
    # not the repo root. `flask run` (FLASK_APP=dashboard.app) also works.
    app.run(debug=True)
