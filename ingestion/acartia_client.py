"""
Acartia API client
===================
Acartia (acartia.io) is a data cooperative for Salish Sea marine mammal
sightings, with founding data contributions from Orca Network and Orcasound.

Confirmed against the real API (2026-08-27, via salish-sea/acartia's
CONTRIBUTING.md and a live request):

  GET https://acartia.io/api/v1/sightings/current

Unauthenticated, no registration required. Returns the last week of
sightings across all species, providers, and trust levels. Live sample
response fields (confirmed, not assumed):

    ssemmi_id, data_source_name, data_source_entity, data_source_id,
    created ("YYYY-MM-DD HH:MM:SS", UTC), photo_url, no_sighted (STRING,
    e.g. "1"), latitude (STRING, e.g. "47.881"), longitude (STRING),
    type (species/ecotype, e.g. "Orca", "Humpback", "Gray Whale",
    "Southern Resident Orca", "Dall's Porpoise", "Unspecified"),
    data_source_witness, trusted (0/1 int), data_source_comments (free
    text -- this is where orca pod mentions live, e.g. "[Orca Network]
    J pod, northbound... (Susan Berta)" -- see normalization/pod_resolver.py),
    profile {name}, entry_id, ssemmi_date_added, submitter_did, signature.

Registration for a Bearer token (needed for historical/trusted-only
endpoints) requires admin approval -- no instant self-serve. This client
works fully unauthenticated against /current today; pass `token` once
approved and it gets added as an Authorization header automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://acartia.io/api/v1"
CURRENT_ENDPOINT = f"{BASE_URL}/sightings/current"
REQUEST_TIMEOUT = 20


class AcartiaClientError(Exception):
    """Raised when the Acartia API can't be reached or returns something we can't parse."""


@dataclass
class AcartiaSighting:
    """Normalized view of one raw Acartia record -- see module docstring for
    the confirmed raw field names this is built from."""

    entry_id: str
    species_raw: str          # Acartia's 'type' field, unnormalized (e.g. "Southern Resident Orca")
    created_utc: datetime
    latitude: float
    longitude: float
    trusted: bool | None
    comments: str
    data_source_entity: str
    data_source_witness: str
    no_sighted: int | None
    photo_url: str

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "AcartiaSighting":
        try:
            created = datetime.strptime(raw["created"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except (KeyError, ValueError) as exc:
            raise AcartiaClientError(f"unparseable 'created' timestamp: {raw.get('created')!r}") from exc

        try:
            lat = float(raw["latitude"])
            lon = float(raw["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AcartiaClientError(
                f"unparseable lat/lon: {raw.get('latitude')!r}, {raw.get('longitude')!r}"
            ) from exc

        no_sighted_raw = raw.get("no_sighted")
        try:
            no_sighted = int(no_sighted_raw) if no_sighted_raw not in (None, "") else None
        except (TypeError, ValueError):
            no_sighted = None

        trusted_raw = raw.get("trusted")
        trusted = bool(trusted_raw) if trusted_raw is not None else None

        return cls(
            entry_id=raw.get("entry_id", ""),
            species_raw=raw.get("type", "") or "",
            created_utc=created,
            latitude=lat,
            longitude=lon,
            trusted=trusted,
            comments=raw.get("data_source_comments", "") or "",
            data_source_entity=raw.get("data_source_entity", "") or "",
            data_source_witness=raw.get("data_source_witness", "") or "",
            no_sighted=no_sighted,
            photo_url=raw.get("photo_url", "") or "",
        )


class AcartiaClient:
    """Thin client over the Acartia sightings API.

    Works fully unauthenticated against /current today. Pass `token` (a
    Bearer token, once your registration is approved -- see module
    docstring) to also enable authenticated endpoints later; unset, this
    client simply omits the Authorization header and sticks to /current.
    """

    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self.token = token
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_current_sightings(self) -> list[AcartiaSighting]:
        """GET /sightings/current -- last 7 days, all species/providers/trust levels.
        Unauthenticated; works with no token at all."""
        try:
            resp = self.session.get(
                CURRENT_ENDPOINT, headers=self._headers(), timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AcartiaClientError(f"request to {CURRENT_ENDPOINT} failed: {exc}") from exc

        try:
            raw_records = resp.json()
        except ValueError as exc:
            raise AcartiaClientError(f"response was not valid JSON: {exc}") from exc

        if not isinstance(raw_records, list):
            raise AcartiaClientError(f"expected a JSON list, got {type(raw_records).__name__}")

        sightings: list[AcartiaSighting] = []
        skipped = 0
        for raw in raw_records:
            try:
                sightings.append(AcartiaSighting.from_raw(raw))
            except AcartiaClientError as exc:
                # One malformed record shouldn't sink the whole batch -- log and continue,
                # same "per-record error handling" spirit as the rest of this project.
                skipped += 1
                logger.warning("skipped unparseable Acartia record: %s", exc)
        if skipped:
            logger.info("Acartia: skipped %d/%d unparseable record(s)", skipped, len(raw_records))

        return sightings


if __name__ == "__main__":
    # Quick manual smoke test: python -m ingestion.acartia_client
    logging.basicConfig(level=logging.INFO)
    client = AcartiaClient()
    results = client.get_current_sightings()
    print(f"Fetched {len(results)} current sightings.")
    for s in results[:5]:
        print(f"  {s.created_utc.isoformat()}  {s.species_raw:25s}  ({s.latitude:.4f}, {s.longitude:.4f})  {s.comments[:60]}")
