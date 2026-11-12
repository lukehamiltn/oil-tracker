"""
Site health check: opens the live site in a real (headless) browser, clicks
through every tab and checks that nothing is broken and the data is fresh.
Run every 3 hours by .github/workflows/health.yml.

If anything is wrong the script exits with an error, so the GitHub job fails
and GitHub emails the repository owner. If the HEALTH_NTFY_CHANNEL secret is
set, it also sends a push notification to that (private) ntfy channel.

Test it on a PC:  BROWSER_CHANNEL=chrome python scripts/health_check.py
"""

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

URL = os.environ.get("SITE_URL", "https://oil-tracker-q7rqjuftmvvqnrgbkzwjcd.streamlit.app/")
# (Strategy lab and Trading bots sit inside Research, so Research comes first)
TABS = ["News", "Market signals", "Event history", "Market conditions", "Scheduled events",
        "Research", "Strategy lab", "Trading bots"]
BROKEN = "This section hit a problem"


# ---------------------------------------------------------------------------
# 1. The live site
# ---------------------------------------------------------------------------
def app_frame(page):
    """The frame the site runs in (on streamlit.app it sits inside an iframe)."""
    for frame in page.frames:
        try:
            if frame.get_by_role("tab", name="Scheduled events").count():
                return frame
        except Exception:
            pass
    return None


def wake_if_asleep(page) -> None:
    for frame in page.frames:
        try:
            button = frame.get_by_role("button", name="get this app back up")
            if button.count():
                print("Site was asleep - waking it up.")
                button.first.click()
                return
        except Exception:
            pass


def check_site() -> list[str]:
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL"))
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, timeout=120_000)
        frame, start = None, time.time()
        while frame is None and time.time() - start < 300:
            wake_if_asleep(page)
            page.wait_for_timeout(5_000)
            frame = app_frame(page)
        if frame is None:
            browser.close()
            return ["The site didn't finish loading within 5 minutes."]
        page.wait_for_timeout(8_000)                       # let the first page settle

        # News tab (open first): topic cards, real headlines, live prices
        cards = frame.locator('[class*="st-key-heat_card_"]').count()
        heads = frame.locator(".headline").count()
        if cards < 6:
            problems.append(f"News: only {cards} topic cards (expected 8).")
        if heads < 8:
            problems.append(f"News: only {heads} headlines shown.")
        if frame.get_by_text("live price unavailable").count():
            problems.append("Header: live oil prices are unavailable (showing last official price).")
        if frame.get_by_text("Headlines are temporarily unavailable").count():
            problems.append("News: headlines are unavailable.")

        # Every tab must load without an error box
        for tab in TABS:
            frame.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(5_000)
            broken = frame.get_by_text(BROKEN).count()
            crashed = frame.locator('[data-testid="stException"]').count()
            if broken or crashed:
                problems.append(f"{tab} tab: a section failed to load.")
            print(f"  {tab}: {'PROBLEM' if broken or crashed else 'ok'}")
        print(f"  news: {cards} topic cards, {heads} headlines")
        browser.close()
    return problems


# ---------------------------------------------------------------------------
# 2. Data freshness (from the files the GitHub jobs keep updating)
# ---------------------------------------------------------------------------
def check_data() -> list[str]:
    problems = []
    now = pd.Timestamp.now(tz="UTC")

    coverage = ROOT / "news_data" / "mc_timelines.csv"
    if coverage.exists():
        newest = pd.read_csv(coverage, parse_dates=["date"]).groupby("topic")["date"].max()
        stale = newest[newest < (now - pd.Timedelta(days=3)).tz_localize(None).normalize()]
        if len(stale):
            problems.append(f"Worldwide coverage (Media Cloud) is out of date for: "
                            f"{', '.join(stale.index)} (last {stale.min():%b %d}).")
        print(f"  worldwide coverage: up to {newest.min():%b %d}")
    else:
        problems.append("Worldwide coverage file is missing.")

    def newest_in(folder: Path, column: str = "time"):
        files = sorted(folder.glob("*.csv"))
        if not files:
            return None
        times = pd.to_datetime(pd.read_csv(files[-1])[column], utc=True, errors="coerce")
        return times.max()

    for name, folder, hours in [("Publisher articles", ROOT / "news_data" / "feeds", 12),
                                ("Benzinga archive", ROOT / "news_data" / "market_news", 26)]:
        newest = newest_in(folder)
        if newest is None:
            problems.append(f"{name}: no saved files.")
            continue
        age = (now - newest).total_seconds() / 3600
        print(f"  {name.lower()}: newest {age:.0f}h old")
        if age > hours:
            problems.append(f"{name}: newest saved story is {age:.0f} hours old.")
    # The hand-kept calendar of OPEC+ meetings and Fed decisions
    calendar = ROOT / "events" / "upcoming.csv"
    if calendar.exists():
        cal = pd.read_csv(calendar, parse_dates=["date"])
        ahead = cal[cal["date"] >= now.tz_localize(None).normalize()]
        for kind, name in [("opec", "OPEC+ meeting"), ("fed", "Fed decision")]:
            if not (ahead["kind"] == kind).any():
                problems.append(f"Calendar: no upcoming {name} dates - add the next ones to "
                                "events/upcoming.csv.")
    return problems


def notify(problems: list[str]) -> None:
    channel = os.environ.get("HEALTH_NTFY_CHANNEL")
    if not channel:
        return
    requests.post("https://ntfy.sh/", timeout=20, json={
        "topic": channel, "title": "Oil Tracker: something needs attention",
        "message": "\n".join(f"- {p}" for p in problems), "tags": ["warning"],
        "click": URL, "priority": 4})


def main() -> int:
    print("Checking the data files...")
    problems = check_data()
    print("Checking the live site...")
    try:
        problems += check_site()
    except Exception as error:
        problems.append(f"The health check itself failed while loading the site: {error!r}")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        notify(problems)
        return 1
    print("\nAll good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
