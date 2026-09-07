"""
Local dashboard -- Flask app wrapping the map, pivot tables, and region
query in a browsable web UI.

Build and test entirely via `flask run` / localhost. No deployment in
this PR -- see README §Phase 2 for the (separate, later) Render step.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import Flask, abort, render_template, request

# Found while wiring up the Acartia token: nothing in this codebase loaded
# .env anywhere, so ALERT_CENTER_LAT/LON/RADIUS_MILES (alerts/geo_filter.py)
# would silently fall back to defaults even when set. Load it here since
# this is an entry point (python -m dashboard.app / flask run).
load_dotenv(Path(__file__).parent.parent / ".env")

from analysis.location_query import known_regions, query_region
from analysis.pivots import location_by_species, pod_by_month, recent_24h_summary, species_by_month
from normalization.pod_resolver import VALID_SPECIES
from storage.db import DEFAULT_DB_PATH, get_connection
from viz.correlations import chinook_cpue_chart, seasonal_chart, tide_height_chart, tide_state_chart
from viz.map import POD_ROWS, build_map

app = Flask(__name__)


def _conn():
    # One short-lived connection per request -- simple and correct for a
    # local, single-user dashboard; not meant to scale past that.
    return get_connection(DEFAULT_DB_PATH)


@app.route("/")
def index():
    conn = _conn()
    try:
        species_counts = {
            species: int(row.sum())
            for species, row in species_by_month(conn).iterrows()
        }
        recent = recent_24h_summary(conn)
    finally:
        conn.close()
    return render_template(
        "index.html", species_counts=species_counts, regions=known_regions(), recent=recent
    )


def _map_filters_from_request() -> dict:
    return dict(
        start_date=request.args.get("start_date") or None,
        end_date=request.args.get("end_date") or None,
        region=request.args.get("region") or None,
        species=request.args.getlist("species") or None,
        pod=request.args.getlist("pod") or None,
        trust=request.args.get("trust") or "all",
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
        )
    finally:
        conn.close()
    return fmap.get_root().render()


@app.route("/pivots")
def pivots_view():
    conn = _conn()
    try:
        tables = {
            "Orca sightings by pod x month": pod_by_month(conn),
            "Sightings by species x month": species_by_month(conn),
            "Sightings by location x species": location_by_species(conn),
        }
    finally:
        conn.close()
    html_tables = {
        title: (df.to_html(classes="pivot-table") if not df.empty else "<p>No data yet.</p>")
        for title, df in tables.items()
    }
    return render_template("pivots.html", tables=html_tables)


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

    conn = _conn()
    try:
        charts = [
            tide_state_chart(conn, start_date=start_date, end_date=end_date, species=species),
            tide_height_chart(conn, start_date=start_date, end_date=end_date, species=species),
            chinook_cpue_chart(conn, start_date=start_date, end_date=end_date, species=species),
            seasonal_chart(conn, start_date=start_date, end_date=end_date, species=species),
        ]
    finally:
        conn.close()

    chart_html = [
        fig.to_html(full_html=False, include_plotlyjs=("cdn" if i == 0 else False))
        for i, fig in enumerate(charts)
    ]

    return render_template(
        "analysis.html",
        chart_html=chart_html,
        all_species=sorted(VALID_SPECIES),
        selected_species=species or [],
        start_date=start_date or "",
        end_date=end_date or "",
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
