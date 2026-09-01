"""
Local dashboard -- Flask app wrapping the map, pivot tables, and region
query in a browsable web UI.

Build and test entirely via `flask run` / localhost. No deployment in
this PR -- see README §Phase 2 for the (separate, later) Render step.
"""

from __future__ import annotations

from flask import Flask, abort, render_template, request

from analysis.location_query import known_regions, query_region
from analysis.pivots import location_by_species, pod_by_month, species_by_month
from storage.db import DEFAULT_DB_PATH, get_connection
from viz.map import build_map

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
    finally:
        conn.close()
    return render_template("index.html", species_counts=species_counts, regions=known_regions())


@app.route("/map")
def map_view():
    region = request.args.get("region") or None
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None

    conn = _conn()
    try:
        fmap = build_map(conn, start_date=start_date, end_date=end_date, region=region)
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
