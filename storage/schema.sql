-- Historical whale sighting trends & migration map -- SQLite schema.
--
-- Matches the spec's `sightings` / `environmental_context` tables, plus two
-- pragmatic additions needed for the feature to actually work:
--   - sightings.external_id / sighting_time: without a stable per-record ID,
--     re-running ingestion would duplicate rows; without a time-of-day (the
--     spec's sighting_date is DATE-only), tide_state can't be computed --
--     "flood/ebb/slack" depends on the moment, not just the day.
--   - source_health: applies the same monitoring pattern used for the live
--     alert's feeds (see whale_alert.py's check_source_health()) to these
--     new ingestion sources, extended with consecutive_zero_runs -- a
--     signal specific to historical/archive-style ingestion, where a source
--     can "succeed" (no error) while still silently returning nothing new
--     for weeks (exactly the Orca Network archive's current, documented
--     state -- see ingestion/orca_network_archive.py).

CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY,
    sighting_date DATE NOT NULL,
    sighting_time TEXT,          -- HH:MM:SS, UTC, when known (Acartia always has it)
    species TEXT NOT NULL,       -- normalized: 'orca', 'humpback', 'gray_whale', 'porpoise', 'dolphin', 'unknown'
    pod_code TEXT,               -- orca only: 'J', 'K', 'L', 'BIGGS_TRANSIENT', 'UNKNOWN'; NULL for non-orca species
    individual_id TEXT,          -- optional, e.g. humpback fluke ID if known (stretch, see README)
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    trusted BOOLEAN,             -- from Acartia 'trusted' flag where available; NULL for sources without a trust concept
    source TEXT NOT NULL,        -- 'orca_network', 'acartia'
    external_id TEXT,            -- source's own stable record ID (Acartia's entry_id), NULL if the source has none
    raw_text TEXT,                -- original report/comments text, for auditability and pod-resolver input
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prevents duplicate ingestion on repeated runs, for sources with a stable ID.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sightings_source_external_id
    ON sightings(source, external_id)
    WHERE external_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sightings_date ON sightings(sighting_date);
CREATE INDEX IF NOT EXISTS idx_sightings_species ON sightings(species);
CREATE INDEX IF NOT EXISTS idx_sightings_location ON sightings(latitude, longitude);

CREATE TABLE IF NOT EXISTS environmental_context (
    sighting_id INTEGER PRIMARY KEY REFERENCES sightings(id),
    chinook_cpue REAL,                  -- orca records only; NULL for other species (see README feature hierarchy)
    tide_height_ft REAL,                -- NOAA CO-OPS, applies across species
    tide_state TEXT,                    -- 'flood', 'ebb', 'slack'
    experimental_moon_phase REAL        -- explicitly flagged as unproven/exploratory, all species
);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    last_success TIMESTAMP,
    last_warned TIMESTAMP,
    consecutive_zero_runs INTEGER NOT NULL DEFAULT 0
);
