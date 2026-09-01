"""
CLI entry point to ingest sightings and regenerate reports.

Usage: python -m ingestion.run_backfill [--season YEAR] [--db PATH]

**Honest scope note:** despite the --season flag (kept for interface
compatibility with the original spec's PR template example), this
currently ingests whatever Acartia's unauthenticated /current endpoint
returns -- the last 7 days, real-time -- not a deep historical backfill.
A true multi-year backfill needs either:
  - Acartia's authenticated historical endpoints (admin-approval-gated,
    not available yet -- see ingestion/acartia_client.py), or
  - Orca Network's archive (not live on their relaunched site yet -- see
    ingestion/orca_network_archive.py).
Both are wired up and will start contributing real historical depth the
moment either becomes available, with zero changes needed here. Until
then, running this regularly (e.g. via the same scheduler as the live
alert) is how historical depth actually accumulates -- one /current
window at a time, deduplicated by (source, external_id) -- rather than
one deep one-shot pull.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, time, timedelta

from analysis.pivots import location_by_species, pod_by_month, species_by_month
from ingestion.acartia_client import AcartiaClient, AcartiaClientError
from ingestion.moon_phase import compute_experimental_moon_phase
from ingestion.orca_network_archive import fetch_archive, OrcaNetworkArchiveError
from ingestion.tide import TideClientError, compute_tide_state, fetch_tide_predictions
from normalization.pod_resolver import normalize_sighting
from storage import db
from storage.db import DEFAULT_DB_PATH
from viz.map import build_map, save_map
from viz.trends import pod_trend_chart, save_chart, species_trend_chart

logger = logging.getLogger(__name__)


def _ingest_acartia(conn) -> int:
    try:
        client = AcartiaClient()
        sightings = client.get_current_sightings()
    except AcartiaClientError as exc:
        logger.error("Acartia ingestion failed: %s", exc)
        db.record_ingestion_failure(conn, "acartia")
        return 0

    records = []
    for s in sightings:
        norm = normalize_sighting(s.species_raw, s.comments)
        records.append({
            "sighting_date": s.created_utc.date().isoformat(),
            "sighting_time": s.created_utc.time().isoformat(),
            "species": norm["species"],
            "pod_code": norm["pod_code"],
            "location_name": None,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "trusted": s.trusted,
            "source": "acartia",
            "external_id": s.entry_id,
            "raw_text": s.comments,
        })
    inserted, duplicates = db.insert_sightings(conn, records)
    db.record_ingestion_run(conn, "acartia", inserted)
    logger.info("Acartia: %d new, %d already seen", inserted, duplicates)
    return inserted


def _ingest_orca_network(conn) -> int:
    try:
        records = fetch_archive()
    except OrcaNetworkArchiveError as exc:
        logger.error("Orca Network archive ingestion failed: %s", exc)
        db.record_ingestion_failure(conn, "orca_network")
        return 0

    # Currently always [] -- see ingestion/orca_network_archive.py. Still
    # recorded as a run (0 new records) so source_health's
    # consecutive_zero_runs correctly reflects reality rather than showing
    # "no recorded successful fetch yet" forever.
    db.record_ingestion_run(conn, "orca_network", len(records))
    logger.info("Orca Network archive: %d record(s) (see module docstring on current status)", len(records))
    return len(records)


def _enrich_environmental_context(conn) -> None:
    """Attach tide state (all species) to every sighting that doesn't have
    it yet. Chinook CPUE and moon phase are added too, per the feature
    hierarchy (CPUE orca-only; moon phase always labeled experimental_)."""
    rows = conn.execute(
        """
        SELECT s.id, s.sighting_date, s.sighting_time, s.species
        FROM sightings s
        LEFT JOIN environmental_context ec ON ec.sighting_id = s.id
        WHERE ec.sighting_id IS NULL AND s.sighting_time IS NOT NULL
        """
    ).fetchall()

    if not rows:
        return

    dates = sorted({date.fromisoformat(r["sighting_date"]) for r in rows})
    try:
        tide_events = fetch_tide_predictions(
            datetime.combine(dates[0], time.min) - timedelta(days=1),
            datetime.combine(dates[-1], time.min) + timedelta(days=1),
        )
    except TideClientError as exc:
        logger.warning("Tide enrichment skipped: %s", exc)
        tide_events = []

    enriched = 0
    for row in rows:
        sighting_dt = datetime.combine(
            date.fromisoformat(row["sighting_date"]),
            time.fromisoformat(row["sighting_time"]),
        )
        tide_state, tide_height = (None, None)
        if tide_events:
            tide_state, tide_height = compute_tide_state(sighting_dt, tide_events)

        context = {
            "chinook_cpue": None,  # see ingestion/chinook_cpue.py -- not yet a verified live source
            "tide_height_ft": tide_height,
            "tide_state": tide_state,
            "experimental_moon_phase": compute_experimental_moon_phase(sighting_dt.date()),
        }
        db.upsert_environmental_context(conn, row["id"], context)
        enriched += 1

    logger.info("Enriched %d sighting(s) with environmental context", enriched)


def _regenerate_reports(conn) -> None:
    fmap = build_map(conn)
    save_map(fmap, "map.html")
    save_chart(species_trend_chart(conn), "trends_species.html")
    save_chart(pod_trend_chart(conn), "trends_pod.html")
    logger.info("Wrote map.html, trends_species.html, trends_pod.html")

    for title, table in (
        ("pod x month", pod_by_month(conn)),
        ("species x month", species_by_month(conn)),
        ("location x species", location_by_species(conn)),
    ):
        logger.info("--- %s ---\n%s", title, table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest whale sightings and regenerate reports.")
    parser.add_argument("--season", type=int, default=None, help="Informational only -- see module docstring.")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.season:
        logger.info(
            "--season %s noted, but only /current (last 7 days) is available today -- see module docstring.",
            args.season,
        )

    db.init_db(args.db)
    conn = db.get_connection(args.db)
    try:
        _ingest_acartia(conn)
        _ingest_orca_network(conn)
        _enrich_environmental_context(conn)
        stale = db.get_stale_sources(conn)
        if stale:
            logger.warning("Stale source(s): %s", [row["source"] for row in stale])
        _regenerate_reports(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
