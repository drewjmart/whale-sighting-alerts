"""
Tests for discord_bot/run_forever.py's backoff logic (2026-10-01) -- the
part of the restart supervisor that's actually unit-testable without a
real Discord bot token or a live subprocess loop.
"""

from discord_bot.run_forever import MAX_BACKOFF_SECONDS, MIN_BACKOFF_SECONDS, _next_backoff


def test_backoff_escalates_on_rapid_repeated_failure():
    # A bad/missing token makes whale_command.run() exit immediately every
    # time -- each such failure should double the wait, not reset it.
    backoff = MIN_BACKOFF_SECONDS
    backoff = _next_backoff(backoff, ran_for_seconds=1)
    assert backoff == MIN_BACKOFF_SECONDS * 2
    backoff = _next_backoff(backoff, ran_for_seconds=0.5)
    assert backoff == MIN_BACKOFF_SECONDS * 4


def test_backoff_caps_at_the_maximum():
    backoff = MAX_BACKOFF_SECONDS
    assert _next_backoff(backoff, ran_for_seconds=1) == MAX_BACKOFF_SECONDS


def test_backoff_resets_after_a_real_run():
    # The bot ran for a while (a real, working connection) before it
    # eventually dropped -- that's not a crash loop, so the next restart
    # shouldn't be throttled by whatever backoff had built up before.
    assert _next_backoff(MAX_BACKOFF_SECONDS, ran_for_seconds=120) == MIN_BACKOFF_SECONDS


def test_backoff_threshold_is_exactly_60_seconds():
    assert _next_backoff(MIN_BACKOFF_SECONDS, ran_for_seconds=60) == MIN_BACKOFF_SECONDS * 2
    assert _next_backoff(MIN_BACKOFF_SECONDS, ran_for_seconds=61) == MIN_BACKOFF_SECONDS
