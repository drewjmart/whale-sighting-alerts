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

Registration for a token requires admin approval -- no instant self-serve
(this client's unauthenticated /current method was built and used during
that wait). Token received and verified live 2026-09-04 -- corrected two
assumptions the wait-period design had made:

  - **Auth mechanism**: the real docs (DOCS.md in salish-sea/acartia) list
    `access_token` as a request PARAMETER on every authenticated endpoint,
    not an `Authorization: Bearer` header. Tested both live against
    `/sightings/trusted` (both returned `200` + `[]`, inconclusive) and
    `/sightings` (only the query-param form returned real data) -- so this
    client sends it as a param, matching the docs and the working test.
  - **What the token actually unlocks**: `GET /sightings` (labeled
    "current sightings, with token" in the docs) is NOT time-limited to 7
    days like its unauthenticated sibling despite the label -- a real pull
    returned 4,176 records back to March 2026, vs. 156 in the public
    /current endpoint for the same moment. This is the real historical
    depth the original spec was waiting on.

Also found and fixed during that same real pull: ~0.7% of authenticated
records (31/4176) use JS `Date.toString()` format for `created`
("Wed Jun 10 2026 05:59:35 GMT+0000 (Coordinated Universal Time)") instead
of the standard format -- `_parse_created()` handles both rather than
silently dropping those records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://acartia.io/api/v1"
CURRENT_ENDPOINT = f"{BASE_URL}/sightings/current"       # unauthenticated, last 7 days
AUTHENTICATED_ENDPOINT = f"{BASE_URL}/sightings"          # token required, NOT time-limited (see module docstring)
TRUSTED_ENDPOINT = f"{BASE_URL}/sightings/trusted"        # token required; returned [] in testing -- see get_trusted_sightings()
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
    def _parse_created(cls, value: str) -> datetime:
        # Confirmed live (2026-09-04, via the authenticated /sightings endpoint):
        # older records use the standard "YYYY-MM-DD HH:MM:SS" format, but ~0.7%
        # (31/4176 in a real pull) use JS Date.toString() instead, e.g.
        # "Wed Jun 10 2026 05:59:35 GMT+0000 (Coordinated Universal Time)" --
        # some client somewhere serialized with str(Date) instead of an ISO
        # format. Try both rather than silently dropping otherwise-good records.
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            core = value.split(" (")[0]  # strip the "(Coordinated Universal Time)" suffix
            return datetime.strptime(core, "%a %b %d %Y %H:%M:%S GMT%z")
        except ValueError:
            raise AcartiaClientError(f"unparseable 'created' timestamp: {value!r}")

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "AcartiaSighting":
        try:
            created = cls._parse_created(raw["created"])
        except KeyError as exc:
            raise AcartiaClientError("missing 'created' timestamp") from exc

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

    `get_current_sightings()` works fully unauthenticated. Pass `token`
    (your approved access token -- see module docstring) to also use
    `get_all_sightings()` (real historical depth, not just 7 days) and
    `get_trusted_sightings()`. Sent as an `access_token` query parameter,
    per the real API docs and a live test -- not an Authorization header.
    """

    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self.token = token
        self.session = session or requests.Session()

    def _fetch(self, url: str, *, requires_token: bool = False) -> list[AcartiaSighting]:
        if requires_token and not self.token:
            raise AcartiaClientError(f"{url} requires a token -- none was provided to this client")

        params = {"access_token": self.token} if self.token else {}
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AcartiaClientError(f"request to {url} failed: {exc}") from exc

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
            logger.info("Acartia (%s): skipped %d/%d unparseable record(s)", url, skipped, len(raw_records))

        return sightings

    def get_current_sightings(self) -> list[AcartiaSighting]:
        """GET /sightings/current -- last 7 days, all species/providers/trust levels.
        Unauthenticated; works with no token at all."""
        return self._fetch(CURRENT_ENDPOINT)

    def get_all_sightings(self) -> list[AcartiaSighting]:
        """GET /sightings (with access_token) -- confirmed live NOT time-limited
        despite the docs' "current sightings" label; a real pull returned 4,176
        records back to March 2026. Requires a token."""
        return self._fetch(AUTHENTICATED_ENDPOINT, requires_token=True)

    def get_trusted_sightings(self) -> list[AcartiaSighting]:
        """GET /sightings/trusted -- returned an empty list in live testing
        (2026-09-04), which may just mean nothing is currently flagged trusted
        via this endpoint rather than indicating a client bug -- the same auth
        mechanism confirmed working on get_all_sightings() is used here.
        Requires a token."""
        return self._fetch(TRUSTED_ENDPOINT, requires_token=True)


if __name__ == "__main__":
    # Quick manual smoke test: python -m ingestion.acartia_client
    logging.basicConfig(level=logging.INFO)
    import os

    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).parent.parent / ".env")
    token = os.environ.get("ACARTIA_API_TOKEN")

    client = AcartiaClient(token=token)
    results = client.get_current_sightings()
    print(f"Fetched {len(results)} current sightings (unauthenticated).")
    for s in results[:5]:
        print(f"  {s.created_utc.isoformat()}  {s.species_raw:25s}  ({s.latitude:.4f}, {s.longitude:.4f})  {s.comments[:60]}")

    if token:
        all_sightings = client.get_all_sightings()
        print(f"\nFetched {len(all_sightings)} sightings (authenticated, full history).")
    else:
        print("\nNo ACARTIA_API_TOKEN set -- skipping authenticated endpoint.")
