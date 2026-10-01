"""
Keeps discord_bot.whale_command's bot process running continuously,
restarting it with backoff if it ever exits -- a crash, a dropped gateway
connection, Discord API trouble, or (until DISCORD_BOT_TOKEN is actually
set) the clean SystemExit whale_command.run() raises when it's missing.

This is what "launch" actually requires for a gateway-based Discord bot:
unlike whale_alert.py's 30-minute fire-and-forget scheduled task, the
bot needs an open connection running at all times, so something has to
notice if it dies and bring it back. Run as its own process (Windows
Task Scheduler: trigger "At startup", action runs this module) rather
than a loop inside whale_command.py itself, so a hard crash in the bot
process can't also take down its own supervisor.

Usage: python -m discord_bot.run_forever
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOG_FILE = BASE_DIR / "discord_bot_runner.log"
LOG_FILE_MAX_BYTES = 1_000_000  # ~1MB, same rotation size as whale_alert.log

MIN_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300  # 5 min cap -- don't hammer Discord's API (or log
                           # the same bad-token error) more than once every
                           # 5 minutes if the bot is failing immediately.

logger = logging.getLogger("discord_bot.run_forever")


def _rotate_log_if_needed() -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_FILE_MAX_BYTES:
            bak = LOG_FILE.with_suffix(LOG_FILE.suffix + ".bak")
            bak.write_bytes(LOG_FILE.read_bytes())
            LOG_FILE.write_text("")
    except OSError as exc:
        logger.warning("Log rotation skipped: %s", exc)


def _next_backoff(current_backoff: int, ran_for_seconds: float) -> int:
    """How long to wait before the next restart attempt.

    Resets to the minimum after a run that lasted a while (a real,
    recovered connection that later dropped) -- only escalates for rapid
    repeated failures (e.g. a missing/bad token causing an immediate
    SystemExit every time), so a brief network blip doesn't get
    throttled into a multi-minute wait on its next legitimate restart.
    """
    if ran_for_seconds > 60:
        return MIN_BACKOFF_SECONDS
    return min(current_backoff * 2, MAX_BACKOFF_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )

    backoff = MIN_BACKOFF_SECONDS
    while True:
        _rotate_log_if_needed()
        logger.info("Starting discord_bot.whale_command ...")
        start = time.monotonic()
        # capture_output + logged after exit (not streamed) -- simple and
        # sufficient here: this is for diagnosing why a restart happened,
        # not watching the bot live (do that by attaching to the process
        # directly, or via Discord itself once it's connected).
        result = subprocess.run(
            [sys.executable, "-m", "discord_bot.whale_command"],
            cwd=str(BASE_DIR), capture_output=True, text=True,
        )
        ran_for = time.monotonic() - start

        if result.stdout:
            logger.info("[whale_command stdout] %s", result.stdout.strip())
        if result.stderr:
            logger.info("[whale_command stderr] %s", result.stderr.strip())
        logger.warning(
            "whale_command exited (code %s) after %.0fs.", result.returncode, ran_for
        )

        # Sleep the CURRENT backoff (so the very first retry actually waits
        # MIN_BACKOFF_SECONDS, not an already-escalated value), then
        # compute the next one for whichever restart follows this one.
        logger.info("Restarting in %ss ...", backoff)
        time.sleep(backoff)
        backoff = _next_backoff(backoff, ran_for)


if __name__ == "__main__":
    main()
