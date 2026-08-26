#!/usr/bin/env python3
"""
Whale Alert Monitor
===================
Monitors West Seattle Blog (RSS), OrcaSound (RSS), and Orca Network (scrape)
for whale sightings and sends you an email (and optionally a Discord webhook
notification) when new posts appear.

SETUP:
  1. Create a venv and install deps:  pip install -r requirements.txt
  2. Copy .env.example to .env and fill in TO_EMAIL / SMTP_USER / SMTP_PASS
     (and optionally DISCORD_WEBHOOK_URL)
  3. Run manually:                    python whale_alert.py
     Test email delivery any time:    python whale_alert.py --test
     Run every 30 min (Windows Task Scheduler or cron):
       */30 * * * * /path/to/python /path/to/whale_alert.py

GMAIL USERS: Use an App Password, not your real password.
  Google Account -> Security -> 2-Step Verification -> App passwords
  https://myaccount.google.com/apppasswords
"""

import argparse
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from astral import LocationInfo
from astral.sun import sun
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ── ENV / CONFIG ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# Windows consoles / redirected log files often default to cp1252, which can't
# encode the emoji used in status output below. Force UTF-8 so this doesn't crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

CONFIG = {
    # Email you want alerts sent TO
    "to_email": os.environ.get("TO_EMAIL", ""),

    # Gmail (or other SMTP) account used to SEND alerts
    # For Gmail: use an App Password, not your real password
    "smtp_user": os.environ.get("SMTP_USER", ""),
    "smtp_pass": os.environ.get("SMTP_PASS", ""),
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,  # SSL port; use 587 + starttls if your provider requires it

    # Optional: Discord webhook URL to also post alerts to a channel.
    # Leave blank in .env to skip Discord notifications entirely.
    "discord_webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", ""),

    # Keywords to match (case-insensitive). Any hit triggers an alert.
    "keywords": [
        "whale", "orca", "humpback", "gray whale", "grey whale",
        "killer whale", "pod", "breach", "spyhop", "cetacean",
        "porpoise", "dolphin", "J pod", "K pod", "L pod",
        "Bigg's", "transient", "southern resident",
        "Alki", "Elliott Bay", "West Seattle",
    ],

    # Where to store seen URLs so we don't re-alert on the same post
    "state_file": BASE_DIR / "whale_alert_state.json",
}

LOG_FILE = BASE_DIR / "whale_alert.log"
LOG_FILE_MAX_BYTES = 1_000_000  # ~1MB

# Source health: a persistently broken feed/scrape (URL changed, markup changed)
# doesn't crash the run -- it just quietly stops producing alerts, which looks
# identical to "nothing's happening out there." These two constants control
# when that silence gets escalated into an actual notification.
STALE_THRESHOLD_HOURS = 48  # ~2 days: generous enough to not flag a quiet feed, tight enough to catch a real break
WARN_COOLDOWN_HOURS = 24    # don't re-send the same warning every 30 min once triggered

# ── LOCATION (for sunrise/sunset) ────────────────────────────────────────────

SEATTLE = LocationInfo("West Seattle", "USA", "America/Los_Angeles", 47.5615, -122.3866)
SEATTLE_TZ = ZoneInfo(SEATTLE.timezone)

# ── SOURCES ───────────────────────────────────────────────────────────────────

SOURCES = [
    {
        "name": "West Seattle Blog",
        "type": "rss",
        # Their dedicated whale category feed
        "url": "https://westseattleblog.com/category/whales/feed/",
        # Fallback: main site feed (broader, more noise)
        # "url": "https://westseattleblog.com/feed/",
    },
    {
        "name": "OrcaSound news",
        "type": "rss",
        # OrcaSound's blog / news RSS
        "url": "https://www.orcasound.net/feed/",
    },
    # Orca Network relaunched their site and no longer has a scrapeable "recent
    # sightings" page — they now point visitors to a private Facebook group,
    # which isn't reliably scrapeable without login. Disabled until they
    # publish a public feed again.
    # {
    #     "name": "Orca Network sightings",
    #     "type": "scrape",
    #     "url": "https://www.orcanetwork.org/recent-sightings",
    #     "selector": ".blog-item-title a, h2.blog-item-title, .entry-title a",
    # },
]

# ── HELPERS ───────────────────────────────────────────────────────────────────

def rotate_log_if_needed() -> None:
    """Keep whale_alert.log under ~1MB by rotating it to a .bak file."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_FILE_MAX_BYTES:
            bak = LOG_FILE.with_suffix(LOG_FILE.suffix + ".bak")
            bak.write_bytes(LOG_FILE.read_bytes())
            LOG_FILE.write_text("")
            print(f"  (log rotated: {LOG_FILE.name} -> {bak.name})")
    except OSError as exc:
        print(f"  ⚠  log rotation skipped: {exc}")


def load_state() -> dict:
    try:
        state = json.loads(CONFIG["state_file"].read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    # source_health tracks, per source name: {"last_success": iso_ts|None, "last_warned": iso_ts|None}
    state.setdefault("seen", [])
    state.setdefault("source_health", {})
    return state


def save_state(state: dict) -> None:
    CONFIG["state_file"].write_text(json.dumps(state, indent=2))


def matches_keywords(text: str) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in CONFIG["keywords"])


def hours_since(iso_ts: str | None) -> float | None:
    """Hours between now and an ISO timestamp, or None if there isn't one / it's unparseable."""
    if not iso_ts:
        return None
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    return (datetime.now(SEATTLE_TZ) - then).total_seconds() / 3600


def record_source_success(source_health: dict, name: str) -> None:
    """Mark a source as successfully fetched+parsed just now. Called on successful
    completion of check_rss()/check_scrape()'s try block -- "success" means the
    fetch/parse didn't raise, regardless of whether anything matched a keyword,
    since most runs legitimately find nothing."""
    entry = source_health.setdefault(name, {"last_success": None, "last_warned": None})
    entry["last_success"] = datetime.now(SEATTLE_TZ).isoformat()


def check_source_health(source_health: dict) -> list[dict]:
    """Log health for every currently-active source and return the ones that are stale.

    Only checks sources currently listed in SOURCES -- a source removed/disabled
    there (like Orca Network below) would otherwise sit stale forever in old
    state files and warn every day for no reason.
    """
    stale = []
    for source in SOURCES:
        name = source["name"]
        health = source_health.get(name, {})
        age = hours_since(health.get("last_success"))
        if age is None:
            print(f"  ?  {name}: no recorded successful fetch yet")
        elif age > STALE_THRESHOLD_HOURS:
            print(f"  ⚠  {name}: last success {age:.0f}h ago, STALE")
            stale.append({"name": name, "last_success": health.get("last_success")})
        else:
            print(f"  ✓  {name}: last success {age:.0f}h ago")
    return stale


def check_credentials() -> None:
    missing = [k for k in ("to_email", "smtp_user", "smtp_pass") if not CONFIG[k]]
    if missing:
        print(f"  ✗  Missing required .env values: {', '.join(missing)}")
        print("  Fill these in whale_alert/.env (see .env.example).")
        sys.exit(1)


def send_email(alerts: list[dict], test_mode: bool = False) -> None:
    """Send a single digest email with all new matches."""
    prefix = "[TEST] " if test_mode else ""
    subject = f"{prefix}🐋 Whale alert — {len(alerts)} new sighting post{'s' if len(alerts) > 1 else ''}"

    # Plain text body
    text_lines = [f"Whale alert — {datetime.now().strftime('%b %d %Y %I:%M %p')}\n"]
    for a in alerts:
        text_lines += [f"[{a['source']}]", f"  {a['title']}", f"  {a['url']}", ""]
    text_body = "\n".join(text_lines)

    # HTML body
    cards = ""
    for a in alerts:
        snippet = a.get("snippet", "")
        snippet_html = f"<p style='margin:6px 0 0;color:#555;font-size:14px'>{snippet}</p>" if snippet else ""
        cards += f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px 16px;margin-bottom:12px">
          <p style="margin:0 0 4px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.05em">{a['source']}</p>
          <p style="margin:0;font-size:16px;font-weight:600">
            <a href="{a['url']}" style="color:#1a73e8;text-decoration:none">{a['title']}</a>
          </p>
          {snippet_html}
        </div>"""

    html_body = f"""
    <html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#1a1a1a">🐋 Whale alert{' (TEST)' if test_mode else ''}</h2>
      <p style="color:#555">{datetime.now().strftime('%B %d, %Y at %I:%M %p')} — {len(alerts)} new post{'s' if len(alerts) > 1 else ''} matched your keywords.</p>
      {cards}
      <hr style="margin:24px 0;border:none;border-top:1px solid #eee">
      <p style="font-size:12px;color:#aaa">
        Sent by whale_alert.py ·
        <a href="https://westseattleblog.com/category/whales/" style="color:#aaa">WSB whales</a> ·
        <a href="https://www.orcanetwork.org/recent-sightings" style="color:#aaa">Orca Network</a> ·
        <a href="https://orcasound.net" style="color:#aaa">OrcaSound</a>
      </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = CONFIG["smtp_user"]
    msg["To"]      = CONFIG["to_email"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(CONFIG["smtp_host"], CONFIG["smtp_port"], context=ctx) as server:
        server.login(CONFIG["smtp_user"], CONFIG["smtp_pass"])
        server.sendmail(CONFIG["smtp_user"], CONFIG["to_email"], msg.as_string())

    print(f"  ✉  Email sent to {CONFIG['to_email']} ({len(alerts)} alert{'s' if len(alerts) > 1 else ''})")


def send_discord(alerts: list[dict], test_mode: bool = False) -> None:
    """Post an embed with all new matches to a Discord webhook, if configured."""
    webhook_url = CONFIG["discord_webhook_url"]
    if not webhook_url:
        print("  ⚠  DISCORD_WEBHOOK_URL not set in .env — skipping Discord notification.")
        return

    prefix = "[TEST] " if test_mode else ""
    title = f"{prefix}🐋 Whale alert — {len(alerts)} new sighting post{'s' if len(alerts) > 1 else ''}"

    # Discord embeds cap at 25 fields, 256 chars/field name, 1024 chars/field value
    fields = []
    for a in alerts[:25]:
        value = a["url"]
        if a.get("snippet"):
            value = f"{a['snippet']}\n{a['url']}"
        fields.append({
            "name": f"[{a['source']}] {a['title']}"[:256],
            "value": value[:1024],
            "inline": False,
        })

    embed = {
        "title": title[:256],
        "color": 0x1A73E8,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
        "footer": {"text": "whale_alert.py"},
    }

    resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()
    print(f"  💬 Discord notification sent ({len(alerts)} alert{'s' if len(alerts) > 1 else ''})")


def send_health_warning(stale_sources: list[dict], test_mode: bool = False) -> bool:
    """Send a low-noise warning that one or more sources haven't had a successful
    fetch in a while -- so a silently broken feed shows up as an actual alert
    instead of just fewer emails over time. Fires independently of whether there
    are whale-sighting alerts this run; reuses the same email/Discord channels,
    each attempted independently (same pattern as the alert senders above).
    Returns True if at least one channel got it out.
    """
    prefix = "[TEST] " if test_mode else ""
    subject = f"{prefix}⚠ Whale Alert Monitor — source health warning"

    lines = [
        f"The following source(s) haven't returned a successful fetch in "
        f"{STALE_THRESHOLD_HOURS}+ hours, which usually means the feed or page format changed:",
        "",
    ]
    for s in stale_sources:
        last = s["last_success"]
        last_str = datetime.fromisoformat(last).strftime("%Y-%m-%d %H:%M") if last else "never"
        lines.append(f"  • {s['name']} (last success: {last_str})")
    body = "\n".join(lines)

    email_ok = False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = CONFIG["smtp_user"]
        msg["To"]      = CONFIG["to_email"]
        msg.attach(MIMEText(body, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(CONFIG["smtp_host"], CONFIG["smtp_port"], context=ctx) as server:
            server.login(CONFIG["smtp_user"], CONFIG["smtp_pass"])
            server.sendmail(CONFIG["smtp_user"], CONFIG["to_email"], msg.as_string())
        print(f"  ✉  Health warning email sent ({len(stale_sources)} stale source(s))")
        email_ok = True
    except Exception as exc:
        print(f"  ✗  Health warning email failed: {exc}")

    discord_ok = False
    webhook_url = CONFIG["discord_webhook_url"]
    if not webhook_url:
        print("  ⚠  DISCORD_WEBHOOK_URL not set in .env — skipping Discord health warning.")
    else:
        try:
            embed = {
                "title": subject[:256],
                "description": body[:4096],
                "color": 0xE67E22,  # amber -- distinct from the blue used for sighting alerts
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "whale_alert.py"},
            }
            resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=15)
            resp.raise_for_status()
            print(f"  💬 Health warning Discord notification sent ({len(stale_sources)} stale source(s))")
            discord_ok = True
        except Exception as exc:
            print(f"  ✗  Health warning Discord notification failed: {exc}")

    return email_ok or discord_ok


# ── SOURCE CHECKS ─────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "WhaleAlertBot/1.0 (personal whale photography alert)"}


def check_rss(source: dict, seen: set, source_health: dict) -> list[dict]:
    alerts = []
    try:
        feed = feedparser.parse(source["url"])
        if feed.bozo and not feed.entries:
            print(f"  ⚠  {source['name']}: feed parse warning")
        for entry in feed.entries:
            url   = entry.get("link", "")
            title = entry.get("title", "")
            body  = entry.get("summary", "") + " " + entry.get("content", [{"value": ""}])[0].get("value", "")
            text  = title + " " + body
            if url and url not in seen and matches_keywords(text):
                # Strip HTML tags from snippet
                snippet = BeautifulSoup(body[:300], "html.parser").get_text()[:200].strip()
                alerts.append({"source": source["name"], "url": url, "title": title, "snippet": snippet})
                seen.add(url)
                print(f"  🐋 [{source['name']}] {title[:80]}")
        # Reached the end without an exception -- fetch+parse succeeded, whether
        # or not anything matched a keyword. That's what "healthy" means here.
        record_source_success(source_health, source["name"])
    except Exception as exc:
        print(f"  ⚠  {source['name']} RSS error: {exc}")
    return alerts


def check_scrape(source: dict, seen: set, source_health: dict) -> list[dict]:
    alerts = []
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select(source["selector"])[:20]
        for link in links:
            href  = link.get("href", "")
            title = link.get_text(strip=True)
            if not href:
                continue
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(source["url"], href)
            if href not in seen and matches_keywords(title):
                alerts.append({"source": source["name"], "url": href, "title": title, "snippet": ""})
                seen.add(href)
                print(f"  🐋 [{source['name']}] {title[:80]}")
        record_source_success(source_health, source["name"])
    except Exception as exc:
        print(f"  ⚠  {source['name']} scrape error: {exc}")
    return alerts


# ── MAIN ──────────────────────────────────────────────────────────────────────

def is_daylight() -> bool:
    """Return True if current time is between today's sunrise and sunset in Seattle."""
    s = sun(SEATTLE.observer, date=datetime.now(SEATTLE_TZ).date(), tzinfo=SEATTLE_TZ)
    now = datetime.now(SEATTLE_TZ)
    return s["sunrise"] <= now <= s["sunset"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Whale Alert Monitor")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Bypass daylight check, skip state file, cap at 3 alerts, and send a real test "
             "email + Discord notification.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rotate_log_if_needed()

    print(f"\n🔍 Whale Alert Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.test:
        print("  🧪 TEST MODE: daylight check bypassed, state file skipped, capped at 3 alerts, "
              "real email + Discord notification will be sent.")

    check_credentials()

    if not args.test and not is_daylight():
        s = sun(SEATTLE.observer, date=datetime.now(SEATTLE_TZ).date(), tzinfo=SEATTLE_TZ)
        rise = s["sunrise"].strftime("%I:%M %p")
        sets = s["sunset"].strftime("%I:%M %p")
        print(f"  Outside daylight hours (today: {rise} – {sets}) — skipping.\n")
        sys.exit(0)

    # Always load real state (so source_health reflects actual history, even in
    # --test) but in test mode ignore the real "seen" list so matches are fresh.
    # source_health mutations below stay in-memory only in test mode, since
    # save_state() is skipped entirely when args.test.
    state = load_state()
    seen = set() if args.test else set(state.get("seen", []))
    source_health = state["source_health"]

    alerts = []
    for source in SOURCES:
        print(f"  Checking {source['name']} ({source['type']}) …")
        if source["type"] == "rss":
            alerts += check_rss(source, seen, source_health)
        elif source["type"] == "scrape":
            alerts += check_scrape(source, seen, source_health)

    if args.test:
        alerts = alerts[:3]
        if not alerts:
            # Nothing matched right now — send a sample alert so delivery can still be verified.
            alerts = [{
                "source": "Test",
                "url": "https://westseattleblog.com/category/whales/",
                "title": "Sample whale sighting alert (no live matches found at test time)",
                "snippet": "This is a placeholder alert sent by --test to confirm email delivery works end-to-end.",
            }]
    else:
        # Trim the seen set so the file doesn't grow forever (keep last 2000 URLs)
        state["seen"] = list(seen)[-2000:]

    # ── Source health check ──────────────────────────────────────────────────
    # Independent of whale-sighting alerts -- a stale source is worth knowing
    # about even on a run that finds nothing to alert on.
    print()
    stale_sources = check_source_health(source_health)
    if stale_sources:
        if args.test:
            # Bypass the cooldown so delivery can be verified the same way
            # --test already verifies whale-alert delivery.
            to_warn = stale_sources
        else:
            to_warn = []
            for s in stale_sources:
                since_warned = hours_since(source_health.get(s["name"], {}).get("last_warned"))
                if since_warned is None or since_warned > WARN_COOLDOWN_HOURS:
                    to_warn.append(s)

        if to_warn:
            print(f"\n  {len(to_warn)} source(s) newly stale or past cooldown — sending health warning …")
            warned = send_health_warning(to_warn, test_mode=args.test)
            if warned and not args.test:
                now_iso = datetime.now(SEATTLE_TZ).isoformat()
                for s in to_warn:
                    source_health.setdefault(s["name"], {})["last_warned"] = now_iso

    if not args.test:
        save_state(state)

    if alerts:
        print(f"\n  Found {len(alerts)} new alert(s) — notifying …")

        # Email and Discord run independently — a failure in one must not block the other.
        email_ok = False
        try:
            send_email(alerts, test_mode=args.test)
            email_ok = True
        except Exception as exc:
            print(f"  ✗  Email failed: {exc}")
            print("  Check SMTP_USER / SMTP_PASS in .env, and that App Passwords are enabled.")

        discord_ok = False
        try:
            send_discord(alerts, test_mode=args.test)
            discord_ok = True
        except Exception as exc:
            print(f"  ✗  Discord notification failed: {exc}")
            print("  Check DISCORD_WEBHOOK_URL in .env.")

        if not email_ok and not discord_ok:
            sys.exit(1)
    else:
        print("  No new whale posts found.")

    print("  Done.\n")


if __name__ == "__main__":
    main()

