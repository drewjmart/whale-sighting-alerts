"""
/whales [region] Discord slash command -- current activity summary,
checkable from your phone, not just from a PC.

**Architecture note, stated plainly rather than glossed over:** this
reuses Acartia's live /current endpoint (not the stored historical DB --
"current activity" means live, not a query over history), and it
CONFIRMED requires a bot process to keep running continuously (this uses
discord.py's gateway/WebSocket connection, not Discord's HTTP Interactions
Endpoint model -- so no public URL is needed, but a persistent process is).
That's a different operational model than the live alert's webhook (which
is a fire-and-forget POST from the 30-min scheduled task) or the local
dashboard (which only needs to run when you're looking at it). Running
this bot 24/7 isn't solved by this PR -- it needs either your machine
staying on, or the Phase 2 Render deployment (see README §Phase 2),
whichever comes first. Documented as a known gap, not silently assumed.

**CONFIRMED (per spec):** the existing alert integration is webhook-only.
The webhook stays exactly as-is for push alerts; this is a SEPARATE,
ADDITIVE bot application (needs its own DISCORD_BOT_TOKEN, with the
applications.commands scope, invited to the server alongside the
existing webhook) purely to handle this slash command. Two integrations
coexist by design -- this module never touches DISCORD_WEBHOOK_URL.

Untestable-without-a-real-bot-token parts (the discord.py Client/gateway
wiring) are kept thin and separate from the testable business logic
(fetching current sightings + formatting a reply), which lives in
build_activity_summary() below and has no Discord dependency at all.

**Naming note:** this package is `discord_bot/`, not `discord/` as the
original spec's file tree suggested -- a package literally named `discord`
shadows the installed discord.py library (any `import discord` inside it
resolves to itself instead of the real library). Found this by actually
trying to construct the bot client, not by inspection; renamed rather
than working around it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Found while wiring up the Acartia token: nothing in this codebase loaded
# .env anywhere, so DISCORD_BOT_TOKEN and ACARTIA_API_TOKEN (used by
# build_activity_summary() below, via AcartiaClient) would silently read
# as unset even when saved. Load it here since this is an entry point
# (python -m discord_bot.whale_command).
load_dotenv(Path(__file__).parent.parent / ".env")

from ingestion.acartia_client import AcartiaClient, AcartiaClientError
from analysis.location_query import _bbox_for_point
from normalization.location_geocoder import _LOCATIONS
from normalization.pod_resolver import normalize_species

logger = logging.getLogger(__name__)

MAX_SIGHTINGS_IN_REPLY = 10


def build_activity_summary(region: str | None = None) -> str:
    """Fetch current Acartia sightings, optionally filtered to a named
    region, and format a Discord-ready text summary. No Discord dependency
    -- fully testable on its own (mock/stub AcartiaClient in tests)."""
    try:
        client = AcartiaClient()
        sightings = client.get_current_sightings()
    except AcartiaClientError as exc:
        return f"⚠️ Couldn't reach Acartia right now: {exc}"

    if region:
        key = region.strip().lower()
        if key not in _LOCATIONS:
            known = ", ".join(sorted(_LOCATIONS.keys()))
            return f"⚠️ Unknown region {region!r}. Try one of: {known}"
        lat, lon = _LOCATIONS[key]
        min_lat, min_lon, max_lat, max_lon = _bbox_for_point(lat, lon, radius_miles=15)
        sightings = [
            s for s in sightings
            if min_lat <= s.latitude <= max_lat and min_lon <= s.longitude <= max_lon
        ]

    if not sightings:
        scope = f"near {region}" if region else "in the last 7 days"
        return f"\U0001f40b No current whale activity reported {scope}."

    lines = [f"\U0001f40b **Current activity{f' near {region}' if region else ''}** ({len(sightings)} report(s)):"]
    for s in sightings[:MAX_SIGHTINGS_IN_REPLY]:
        species = normalize_species(s.species_raw)
        comment = (s.comments[:80] + "…") if len(s.comments) > 80 else s.comments
        lines.append(f"- {s.created_utc:%b %d %H:%M} UTC — **{species}** ({s.species_raw}): {comment}")

    if len(sightings) > MAX_SIGHTINGS_IN_REPLY:
        lines.append(f"...and {len(sightings) - MAX_SIGHTINGS_IN_REPLY} more.")

    return "\n".join(lines)


def _build_bot():
    """Discord wiring -- imports discord.py lazily so build_activity_summary()
    and its tests never need a real bot token or network gateway."""
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready():
        await tree.sync()
        logger.info("whale_command bot ready as %s", client.user)

    @tree.command(name="whales", description="Current whale activity, optionally near a region")
    @app_commands.describe(region="A known region name, e.g. 'san juan island' (optional)")
    async def whales(interaction, region: str | None = None):
        await interaction.response.defer()
        summary = build_activity_summary(region)
        await interaction.followup.send(summary)

    return client


def run() -> None:
    """Entry point: `python -m discord_bot.whale_command`. Requires
    DISCORD_BOT_TOKEN in .env -- separate from DISCORD_WEBHOOK_URL."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "DISCORD_BOT_TOKEN not set in .env. This is a separate bot application "
            "from the existing DISCORD_WEBHOOK_URL -- see module docstring."
        )
    client = _build_bot()
    client.run(token)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
