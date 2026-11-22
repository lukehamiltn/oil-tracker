"""
Spike alerts: a push notification when an oil news topic starts spiking,
with what history says happened after past spikes in that topic.

Sent through ntfy.sh, a free notification service: anyone can subscribe to
the channel below in the ntfy app or browser, with no account. Run every 3
hours by .github/workflows/alerts.yml (after the news refresh).

Each topic alerts at most once per spike: the dates sent are remembered in
news_data/alerts_sent.json, and a topic can alert again only after
news.COOLDOWN_DAYS.

Natural gas has its own channel (GAS_CHANNEL): `--gas` checks the gas news
topics instead and sends there. Gas topics are remembered as "gas:<topic>".

Run it yourself:
    python alerts.py --dry-run          # print what would be sent, send nothing
    python alerts.py --test             # send one test message to the channel
    python alerts.py --gas --dry-run    # the same for natural gas
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
GAS_CHANNEL = "gastracker-q7rq-alerts"
GAS_SITE_URL = SITE_URL + "gas"
GAS_SUBSCRIBE_URL = NTFY_URL + GAS_CHANNEL
STATE_PATH = Path(__file__).parent / "news_data" / "alerts_sent.json"


def send(title: str, message: str, tags: list[str], gas: bool = False) -> None:
    channel, site = (GAS_CHANNEL, GAS_SITE_URL) if gas else (CHANNEL, SITE_URL)
    label = "Open Natural Gas Tracker" if gas else "Open Oil Tracker"
    response = requests.post(NTFY_URL, timeout=20, json={
        "topic": channel, "title": title, "message": message, "tags": tags,
        "click": site, "actions": [{"action": "view", "label": label, "url": site}]})
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
    timelines = news.load_worldwide()      # Media Cloud (same as the website)
    archive = mn.load_archive()
    heat, source = news.heat_now(timelines, mn.topic_timelines(archive))
    hot = heat[(heat["heat"] >= news.SPIKE_RATIO) & heat["enough"] & heat["big_enough"]]
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
        if pd.notna(getattr(r, "distinct", float("nan"))):
            lines.append(f"{r.articles_3d:,} articles, {int(r.distinct)}"
                         f"{'+' if r.distinct_capped else ''} distinct stories.")
        if r.one_day:
            lines.append(f"Mostly one day: {r.peak_articles} of {r.articles_3d} stories came on "
                         f"{r.peak_day:%b} {r.peak_day.day}"
                         + (", OPEC's monthly report day (no policy decision)."
                            if getattr(r, "report_day", False) else "."))
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


def gas_headline(topic: str) -> str | None:
    """The newest gas headline about this topic from the publishers' feeds."""
    try:
        import news_feeds as nf
        pool = nf.fetch(oil_only=False)
    except Exception as error:
        print(f"News feeds unavailable: {error!r}")
        return None
    if pool.empty:
        return None
    hits = pool[pool["headline"].fillna("").map(lambda h: topic in news.classify_gas(h))]
    return hits.sort_values("time")["headline"].iloc[-1] if len(hits) else None


def main_gas(dry_run: bool = False) -> None:
    """Alerts for natural gas news spikes, sent to the gas channel."""
    import gas_review
    import mediacloud_news
    timelines = mediacloud_news.load(mediacloud_news.GAS_PATH)
    if timelines.empty:
        print("No gas coverage saved yet.")
        return
    heat = news.current_heat(timelines)
    hot = heat[(heat["heat"] >= news.SPIKE_RATIO) & heat["enough"] & heat["big_enough"]]
    print("Gas coverage: " + ", ".join(f"{r.topic} {r.heat:.1f}x" for r in heat.itertuples()))
    state = load_state()
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    due = [r for r in hot.itertuples()
           if f"gas:{r.topic}" not in state
           or (today - pd.Timestamp(state[f"gas:{r.topic}"])).days >= news.COOLDOWN_DAYS]
    if not due:
        print("No new gas spikes to alert on.")
        return
    data = gas_review.build_data()
    results = data["spike_react"][0]
    for r in due:
        title = f"{r.label}: gas news coverage {r.heat:.1f}x normal"
        lines = [f"{r.articles_3d:,} articles in the last 3 days."]
        headline = gas_headline(r.topic)
        if headline:
            lines.append(f"Latest: {headline}")
        week = results.loc[results["topic"] == r.topic, "day_5_pct"].dropna() if not results.empty else []
        if len(week):
            verdict = data["sig"].check("NATGAS", 5, week)
            lines.append(f"After {len(week)} past spikes, Henry Hub averaged {week.mean():+.1f}% over the "
                         f"next week and rose {(week > 0).mean():.0%} of the time "
                         f"({mk.VERDICTS[verdict][0].lower()}).")
        lines.append("History, not a forecast.")
        message = "\n\n".join(lines)
        print(f"\n--- {title}\n{message}")
        if not dry_run:
            send(title, message, ["fire", "chart_with_upwards_trend"], gas=True)
            state[f"gas:{r.topic}"] = f"{today:%Y-%m-%d}"
    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    parser.add_argument("--test", action="store_true", help="send one test message")
    parser.add_argument("--weekly", action="store_true",
                        help="send the Saturday 'week in review' summary")
    parser.add_argument("--gas", action="store_true", help="natural gas instead of oil")
    args = parser.parse_args()
    if args.gas and args.weekly:
        import gas_review
        title, message = gas_review.weekly_message(gas_review.build_data())
        print(title)
        print(message)
        if not args.dry_run:
            send(title, message, ["calendar"], gas=True)
    elif args.gas and args.test:
        send("Natural Gas Tracker alerts are working",
             "You'll get a message here when a natural gas news topic starts spiking, "
             "with what happened after past spikes.", ["white_check_mark"], gas=True)
        print(f"Test message sent to {GAS_SUBSCRIBE_URL}")
    elif args.gas:
        main_gas(dry_run=args.dry_run)
    elif args.weekly:
        import recap
        title, message = recap.weekly_message(recap.build_data())
        print(title)
        print(message)
        if not args.dry_run:
            send(title, message, ["calendar"])
    elif args.test:
        send("Oil Tracker alerts are working",
             "You'll get a message here when an oil news topic starts spiking, "
             "with what happened after past spikes.", ["white_check_mark"])
        print(f"Test message sent to {SUBSCRIBE_URL}")
    else:
        main(dry_run=args.dry_run)
