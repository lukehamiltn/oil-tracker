"""
Spike alerts: a push notification when an oil news topic starts spiking,
with what history says happened after past spikes in that topic.

Sent through ntfy.sh, a free notification service: anyone can subscribe to
the channel below in the ntfy app or browser, with no account. Run every 3
hours by .github/workflows/alerts.yml (after the news refresh).

Each topic alerts at most once per spike: the dates sent are remembered in
news_data/alerts_sent.json, and a topic can alert again only after
news.COOLDOWN_DAYS.

Run it yourself:
    python alerts.py --dry-run    # print what would be sent, send nothing
    python alerts.py --test       # send one test message to the channel
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import requests

import fetch_prices
import market_news as mn
import markets as mk
import news

CHANNEL = "oiltracker-q7rq-alerts"
NTFY_URL = "https://ntfy.sh/"
SITE_URL = "https://oil-tracker-q7rqjuftmvvqnrgbkzwjcd.streamlit.app/"
SUBSCRIBE_URL = NTFY_URL + CHANNEL
STATE_PATH = Path(__file__).parent / "news_data" / "alerts_sent.json"


def send(title: str, message: str, tags: list[str]) -> None:
    response = requests.post(NTFY_URL, timeout=20, json={
        "topic": CHANNEL, "title": title, "message": message, "tags": tags,
        "click": SITE_URL, "actions": [{"action": "view", "label": "Open Oil Tracker",
                                        "url": SITE_URL}]})
    response.raise_for_status()


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def history_lines(topic: str, by_market: dict, sig: mk.Significance) -> list[str]:
    """What happened after past spikes in this topic: Brent, plus any market
    where the pattern passes the 'is it real?' check."""
    lines, strong = [], []
    for key, (results, _) in by_market.items():
        if results.empty:
            continue
        week = results.loc[results["topic"] == topic, "day_5_pct"].dropna()
        if week.empty:
            continue
        verdict = sig.check(key, 5, week)
        name = mk.MARKETS[key][1]
        if key == "BRENT":
            lines.append(f"After {len(week)} past spikes, Brent averaged {week.mean():+.1f}% "
                         f"over the next week and rose {(week > 0).mean():.0%} of the time "
                         f"({mk.VERDICTS[verdict][0].lower()}).")
        elif verdict in ("strong", "possible"):
            strong.append(f"{name} {week.mean():+.1f}% ({verdict})")
    if strong:
        lines.append("Clearer patterns: " + ", ".join(strong) + ".")
    return lines


def latest_headline(archive: pd.DataFrame, topic: str) -> str | None:
    recent = archive[archive["time"] >= archive["time"].max() - pd.Timedelta(hours=48)]
    hits = recent[mn.topic_match(recent, {"topic": topic})]
    return hits.sort_values("time")["headline"].iloc[-1] if len(hits) else None


def main(dry_run: bool = False) -> None:
    timelines = news.load_timelines()
    archive = mn.load_archive()
    heat, source = news.heat_now(timelines, mn.topic_timelines(archive))
    hot = heat[(heat["heat"] >= news.SPIKE_RATIO) & heat["enough"]]
    print(f"Coverage from {source}: " + ", ".join(
        f"{r.topic} {r.heat:.1f}x" for r in heat.itertuples()))
    state = load_state()
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    due = [r for r in hot.itertuples()
           if r.topic not in state
           or (today - pd.Timestamp(state[r.topic])).days >= news.COOLDOWN_DAYS]
    if not due:
        print("No new spikes to alert on.")
        return

    # Past reactions in every market (prices first, so the history is current)
    fetch_prices.main()
    markets = mk.load_markets()
    sig = mk.Significance(markets)
    spikes = news.all_spikes(timelines) if source == "world" else \
        news.all_spikes(mn.topic_timelines(archive), "market")
    by_market = mk.reactions(markets, spikes)

    for r in due:
        title = f"{r.label}: news coverage {r.heat:.1f}x normal"
        lines = []
        headline = latest_headline(archive, r.topic)
        if headline:
            lines.append(f"Latest: {headline}")
        lines += history_lines(r.topic, by_market, sig)
        lines.append("History, not a forecast.")
        message = "\n\n".join(lines)
        print(f"\n--- {title}\n{message}")
        if not dry_run:
            send(title, message, ["oil_drum", "chart_with_upwards_trend"])
            state[r.topic] = f"{today:%Y-%m-%d}"
    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    parser.add_argument("--test", action="store_true", help="send one test message")
    args = parser.parse_args()
    if args.test:
        send("Oil Tracker alerts are working",
             "You'll get a message here when an oil news topic starts spiking, "
             "with what happened after past spikes.", ["white_check_mark"])
        print(f"Test message sent to {SUBSCRIBE_URL}")
    else:
        main(dry_run=args.dry_run)
