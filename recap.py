"""
Week in review: how markets moved, what made the news, and - for each news
spike and scheduled event - what history suggested vs what actually happened.
Also a running track record: how often history pointed the right way.

"What history suggested" only uses events from BEFORE each one (no hindsight).
"What happened" is Brent's move over the next 5 trading days, from the close
before the event, using official prices carried up to today with futures
(live_prices.extend).
"""

import pandas as pd

import event_study as es
import fed_events as fed
import inventory_events as inv
import live_prices
import markets as mk
import news

WEEK_MARKETS = ["BRENT", "WTI", "GASOLINE", "HEATING_OIL", "NATGAS", "XLE", "DOLLAR"]
HORIZON = 5
CAT_COL = {"news": "topic", "inventory": "category", "opec": "decision", "fed": "decision"}


def weeks(n: int = 8) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """The last n trading weeks as (Monday, Friday), newest first. On a
    weekend the newest is the week that just finished."""
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    monday = today - pd.Timedelta(days=today.weekday())
    return [(monday - pd.Timedelta(weeks=w), monday - pd.Timedelta(weeks=w) + pd.Timedelta(days=4))
            for w in range(n)]


def market_closes(span: str = "1y") -> dict[str, pd.Series]:
    """Recent daily closes for every market in the recap (futures for the oil markets)."""
    return {m: live_prices.daily_closes(m, span=span) for m in WEEK_MARKETS}


def week_move(closes: pd.Series, monday: pd.Timestamp, friday: pd.Timestamp) -> float | None:
    """% change from the last close before Monday to the last close up to Friday."""
    if closes.empty:
        return None
    before = closes[closes.index < monday]
    during = closes[(closes.index >= monday) & (closes.index <= friday)]
    if before.empty or during.empty:
        return None
    return (during.iloc[-1] / before.iloc[-1] - 1) * 100


def topic_week(timelines: pd.DataFrame, monday: pd.Timestamp, friday: pd.Timestamp) -> pd.DataFrame:
    """Each topic's share of all news that week vs its normal share (previous 60 days)."""
    rows = []
    for topic, t in timelines.groupby("topic"):
        t = t.set_index("date").sort_index()
        share = t["articles"] / t["all_articles"].where(t["all_articles"] > 0)
        week = t[(t.index >= monday) & (t.index <= friday)]
        normal = share[(share.index < monday) & (share.index >= monday - pd.Timedelta(days=60))].median()
        if week.empty or not normal:
            continue
        ratio = (week["articles"].sum() / week["all_articles"].sum()) / normal
        rows.append({"topic": topic, "label": news.TOPICS[topic]["label"],
                     "ratio": ratio, "articles": int(week["articles"].sum())})
    return pd.DataFrame(rows).sort_values("ratio", ascending=False) if rows else pd.DataFrame()


def actual_move(prices: pd.Series, event_date: pd.Timestamp) -> tuple[float | None, int]:
    """Brent's % move over the next HORIZON trading days, from the close before
    the event. Returns (move, trading days available); a move of fewer than
    HORIZON days means the week isn't over yet."""
    base = prices.index.searchsorted(event_date) - 1
    if base < 0:
        return None, 0
    end = min(base + HORIZON, len(prices) - 1)
    days = end - base
    if days <= 0:
        return None, 0
    return (prices.iloc[end] / prices.iloc[base] - 1) * 100, days


def _label(kind: str, category: str) -> str:
    if kind == "news":
        return news.TOPICS[category]["label"] + " (news spike)"
    if kind == "inventory":
        return "EIA report: " + inv.LABELS[category]
    if kind == "opec":
        return "OPEC+: " + es.LABELS[category]
    return "Fed: " + fed.LABELS[category]


def expectation(data: dict, kind: str, category: str, date: pd.Timestamp) -> dict:
    """What past events of the same type (strictly before `date`) suggested for
    Brent's next week: average move, share that rose, count and verdict."""
    results = data["react"][kind]["BRENT"][0]
    if results.empty:
        return {"n": 0}
    past = results[(results[CAT_COL[kind]] == category) & (results["date"] < date)]
    week = past[f"day_{HORIZON}_pct"].dropna()
    if week.empty:
        return {"n": 0}
    return {"n": len(week), "avg": week.mean(), "up": (week > 0).mean(),
            "verdict": data["sig"].check("BRENT", HORIZON, week)}


def events_between(data: dict, start: pd.Timestamp, end: pd.Timestamp,
                   big_eia_only: bool = False) -> pd.DataFrame:
    """News spikes and scheduled events dated in [start, end]."""
    rows = []
    for kind, events in data["events"].items():
        if kind not in CAT_COL or events.empty:
            continue
        day_col = "spike_day" if kind == "news" else "date"
        hit = events[(events[day_col] >= start) & (events[day_col] <= end)]
        if kind == "inventory" and big_eia_only:
            hit = hit[hit["category"].isin(["big_draw", "big_build"])]
        for _, e in hit.iterrows():
            rows.append({"kind": kind, "date": e["date"], "day": e[day_col],
                         "category": e[CAT_COL[kind]], "label": _label(kind, e[CAT_COL[kind]]),
                         "detail": e.get("headline") or e.get("description") or ""})
    return pd.DataFrame(rows).sort_values("day") if rows else pd.DataFrame()


def scored(data: dict, prices: pd.Series, events: pd.DataFrame) -> pd.DataFrame:
    """Add what history suggested and what happened to each event."""
    if events.empty:
        return events
    out = []
    for _, e in events.iterrows():
        exp = expectation(data, e["kind"], e["category"], e["date"])
        move, days = actual_move(prices, e["date"])
        row = dict(e)
        row.update({"n_past": exp["n"], "expected": exp.get("avg"), "rose_share": exp.get("up"),
                    "verdict": exp.get("verdict", "few"), "actual": move, "days": days})
        if exp["n"] >= mk.MIN_EVENTS and move is not None and days == HORIZON:
            row["right_way"] = (exp["avg"] > 0) == (move > 0)
        else:
            row["right_way"] = None
        out.append(row)
    return pd.DataFrame(out)


def track_record(data: dict, prices: pd.Series, months: int = 6) -> pd.DataFrame:
    """Every news spike, OPEC+/Fed decision and big EIA surprise in the last
    `months`, scored (only those with a finished week count)."""
    end = prices.index[-1]
    start = end - pd.DateOffset(months=months)
    events = events_between(data, start, end, big_eia_only=True)
    t = scored(data, prices, events)
    return t[t["right_way"].notna()] if not t.empty else t


# ---------------------------------------------------------------------------
# The Saturday summary (sent by alerts.py --weekly)
# ---------------------------------------------------------------------------
def build_data() -> dict:
    """Everything the recap needs, built from scratch (for the GitHub job)."""
    import fetch_prices
    import market_data as md
    import market_news as mn
    for job in (fetch_prices.main, inv.download_inventories, md.main, fed.download_fed):
        try:
            job()
        except Exception as error:
            print(f"Download failed, using saved data: {error}")
    markets = mk.load_markets()
    archive = mn.load_archive()
    timelines = news.load_worldwide()
    events = {"opec": es.load_events(), "inventory": inv.build_events(inv.load_inventories()),
              "fed": fed.build_events(fed.load_fed()),
              "news": mn.add_headlines(news.all_spikes(timelines), archive, mn.topic_match)}
    return {"events": events, "timelines": timelines, "sig": mk.Significance(markets),
            "react": {k: mk.reactions(markets, e) for k, e in events.items()},
            "prices": es.load_prices()}


def weekly_message(data: dict) -> tuple[str, str]:
    """(title, message) summing up the week that just finished."""
    monday, friday = weeks(1)[0]
    closes = market_closes()
    prices, _ = live_prices.extend(data["prices"])
    moves = [f"{mk.MARKETS[m][1]} {move:+.1f}%" for m in WEEK_MARKETS
             if (move := week_move(closes[m], monday, friday)) is not None]
    title = f"Oil week of {monday:%b} {monday.day}–{friday.day}: " + (moves[0] if moves else "")
    lines = []
    if moves:
        lines.append("Markets: " + ", ".join(moves) + ".")
    topics = topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        lines.append("Most covered: " + ", ".join(
            f"{r.label} ({r.ratio:.1f}x normal)" for r in topics.head(2).itertuples()) + ".")
    events = scored(data, prices, events_between(data, monday, friday))
    for _, e in events.iterrows() if not events.empty else []:
        said = (f"history said {e['expected']:+.1f}%" if e["n_past"] else "no history")
        got = "" if e["actual"] is None else f", Brent {e['actual']:+.1f}% since"
        lines.append(f"{e['day']:%a}: {e['label']} ({said}{got}).")
    record = track_record(data, prices)
    if len(record):
        lines.append(f"Track record (6 months): history pointed the right way "
                     f"{int(record['right_way'].sum())} of {len(record)} times.")
    lines.append("History, not a forecast.")
    return title, "\n".join(lines)
