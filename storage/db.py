"""
Storage read/write layer over the SQLite schema in schema.sql.

Deliberately thin -- a handful of functions over sqlite3, not an ORM.
Everything here operates on plain dicts, matching the normalized-record
shape produced by ingestion/*.py + normalization/*.py.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).parent.parent
DEFAULT_DB_PATH = BASE_DIR / "whale_sightings.sqlite3"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

STALE_THRESHOLD_HOURS = 48  # same constant/spirit as whale_alert.py's live-alert health check


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


# ── Sightings ─────────────────────────────────────────────────────────────

def insert_sighting(conn: sqlite3.Connection, record: dict[str, Any]) -> int | None:
    """Insert one normalized sighting. Returns the new row id, or None if it
    was a duplicate (same source + external_id already present) and was
    silently skipped -- that's expected on a re-run, not an error."""
    try:
        cur = conn.execute(
            """
            INSERT INTO sightings
                (sighting_date, sighting_time, species, pod_code, individual_id,
                 location_name, latitude, longitude, trusted, source, external_id, raw_text)
            VALUES (:sighting_date, :sighting_time, :species, :pod_code, :individual_id,
                    :location_name, :latitude, :longitude, :trusted, :source, :external_id, :raw_text)
            """,
            {
                "sighting_date": record["sighting_date"],
                "sighting_time": record.get("sighting_time"),
                "species": record["species"],
                "pod_code": record.get("pod_code"),
                "individual_id": record.get("individual_id"),
                "location_name": record.get("location_name"),
                "latitude": record.get("latitude"),
                "longitude": record.get("longitude"),
                "trusted": record.get("trusted"),
                "source": record["source"],
                "external_id": record.get("external_id"),
                "raw_text": record.get("raw_text"),
            },
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate (source, external_id) -- expected on re-ingestion, not an error


def insert_sightings(conn: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """Bulk insert. Returns (inserted_count, duplicate_count)."""
    inserted = duplicates = 0
    for record in records:
        row_id = insert_sighting(conn, record)
        if row_id is None:
            duplicates += 1
        else:
            inserted += 1
    conn.commit()
    return inserted, duplicates


def query_sightings(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    species: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,  # (min_lat, min_lon, max_lat, max_lon)
) -> list[sqlite3.Row]:
    """Flexible query used by both analysis/pivots.py (no location filter --
    trend analysis covers all WA waters) and analysis/location_query.py
    (bbox set -- "what's near San Juan Island"). See spec §1a: these are
    the same underlying data, queried two different ways for two different
    purposes -- this function is the shared plumbing, not a merged filter."""
    clauses = []
    params: dict[str, Any] = {}

    if start_date:
        clauses.append("sighting_date >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("sighting_date <= :end_date")
        params["end_date"] = end_date
    if species:
        clauses.append("species = :species")
        params["species"] = species
    if bbox:
        min_lat, min_lon, max_lat, max_lon = bbox
        clauses.append("latitude BETWEEN :min_lat AND :max_lat")
        clauses.append("longitude BETWEEN :min_lon AND :max_lon")
        params.update(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM sightings {where} ORDER BY sighting_date DESC, sighting_time DESC"
    return conn.execute(sql, params).fetchall()


# ── Environmental context ───────────────────────────────────────────────

def upsert_environmental_context(conn: sqlite3.Connection, sighting_id: int, context: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO environmental_context
            (sighting_id, chinook_cpue, tide_height_ft, tide_state, experimental_moon_phase)
        VALUES (:sighting_id, :chinook_cpue, :tide_height_ft, :tide_state, :experimental_moon_phase)
        ON CONFLICT(sighting_id) DO UPDATE SET
            chinook_cpue = excluded.chinook_cpue,
            tide_height_ft = excluded.tide_height_ft,
            tide_state = excluded.tide_state,
            experimental_moon_phase = excluded.experimental_moon_phase
        """,
        {
            "sighting_id": sighting_id,
            "chinook_cpue": context.get("chinook_cpue"),
            "tide_height_ft": context.get("tide_height_ft"),
            "tide_state": context.get("tide_state"),
            "experimental_moon_phase": context.get("experimental_moon_phase"),
        },
    )
    conn.commit()


# ── Source health ────────────────────────────────────────────────────────
# Same pattern as whale_alert.py's live-alert health check (last_success,
# STALE_THRESHOLD_HOURS), extended with consecutive_zero_runs -- useful here
# specifically because a historical/archive source can "succeed" (no
# exception) while returning zero new records run after run, which is a
# meaningfully different signal than an outright fetch failure.

def record_ingestion_run(conn: sqlite3.Connection, source: str, new_record_count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT consecutive_zero_runs FROM source_health WHERE source = ?", (source,)).fetchone()
    if new_record_count > 0:
        zero_runs = 0
    else:
        zero_runs = (row["consecutive_zero_runs"] if row else 0) + 1

    conn.execute(
        """
        INSERT INTO source_health (source, last_success, consecutive_zero_runs)
        VALUES (:source, :now, :zero_runs)
        ON CONFLICT(source) DO UPDATE SET
            last_success = excluded.last_success,
            consecutive_zero_runs = excluded.consecutive_zero_runs
        """,
        {"source": source, "now": now, "zero_runs": zero_runs},
    )
    conn.commit()


def record_ingestion_failure(conn: sqlite3.Connection, source: str) -> None:
    """A real fetch/parse error -- last_success is NOT touched, matching the
    live-alert pattern where only a successful fetch/parse updates it."""
    conn.execute(
        "INSERT OR IGNORE INTO source_health (source) VALUES (?)", (source,)
    )
    conn.commit()


def get_stale_sources(conn: sqlite3.Connection, threshold_hours: float = STALE_THRESHOLD_HOURS) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM source_health").fetchall()
    stale = []
    now = datetime.now(timezone.utc)
    for row in rows:
        if row["last_success"] is None:
            stale.append(row)
            continue
        last = datetime.fromisoformat(row["last_success"])
        age_hours = (now - last).total_seconds() / 3600
        if age_hours > threshold_hours:
            stale.append(row)
    return stale
