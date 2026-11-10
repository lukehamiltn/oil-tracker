"""
News: match today's oil news to similar moments in the past, and show what
the oil market did next.

Source: the GDELT Project (gdeltproject.org), a free database that monitors
news worldwide. For each news TOPIC (e.g. "attacks on tankers") we save how
much of the world's news coverage it got every day since 2017.

The latest headlines, the search box and a second, market-news view of each
topic come from market_news.py (Alpaca/Benzinga), because GDELT's rate
limits make live requests from the website unreliable.

A "news spike" is a day when a topic suddenly got far more coverage than
usual (at least 3x its normal share of all news). Each spike is treated as
an event, and we measure how Brent moved afterwards - just like the OPEC+,
EIA and Fed event studies.

The history is refreshed once a day by a GitHub Action
(.github/workflows/news.yml), which saves it to news_data/timelines.csv, so
the website loads it instantly instead of querying GDELT on every visit.

Run it with:
    python news.py update           refresh the topic history (slow: GDELT rate limits)
"""

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HISTORY_START = "20170101000000"     # GDELT's searchable history starts in 2017
TIMELINES_PATH = Path(__file__).parent / "news_data" / "timelines.csv"

# How a spike is defined (chosen for a sensible NUMBER of spikes per topic,
# never by looking at what oil did afterwards)
SPIKE_RATIO = 3.0        # coverage at least 3x its normal share...
MIN_ARTICLES = 20        # ...with at least this many articles that day
BASELINE_DAYS = 60       # "normal" = median share over the previous 60 days
COOLDOWN_DAYS = 30       # a new spike needs 30 days of separation

# Each topic: label, GDELT search query, headline keywords (regex), colour
TOPICS = {
    "shipping": {
        "label": "Attacks on tankers & shipping lanes",
        "query": '(tanker OR "Strait of Hormuz" OR "Red Sea" OR Houthi) (attack OR seized OR missile OR drone)',
        "keywords": r"tanker|hormuz|red sea|houthi|shipping lane|bab.el.mandeb",
        "color": "#2a78d6",
    },
    "infrastructure": {
        "label": "Attacks & outages at oil facilities",
        "query": '(refinery OR pipeline OR oilfield OR "oil facility" OR "oil facilities") (attack OR explosion OR drone OR outage OR fire)',
        "keywords": r"refiner|pipeline|oil ?field|oil facilit|terminal|abqaiq|outage",
        "color": "#eb6834",
    },
    "sanctions": {
        "label": "Oil sanctions & embargoes",
        "query": '(sanctions OR embargo OR "price cap") (oil OR crude)',
        "keywords": r"sanction|embargo|price cap",
        "color": "#1baf7a",
    },
    "opec": {
        "label": "OPEC+ supply decisions",
        "query": "OPEC (output OR production OR cut OR cuts OR quota)",
        "keywords": r"opec",  # GDELT queries can't contain "+", so "OPEC" covers OPEC+
        "color": "#eda100",
    },
    "middle_east": {
        "label": "Middle East conflict",
        "query": '(Iran OR Israel OR Iraq OR Saudi OR Yemen) (war OR strike OR airstrike OR missile) oil',
        "keywords": r"\biran|israel|iraq|saudi|yemen|gaza|lebanon|hezbollah",
        "color": "#e87ba4",
    },
    "hurricane": {
        "label": "Hurricanes hitting U.S. oil",
        "query": 'hurricane ("Gulf of Mexico" OR "Gulf Coast" OR refineries OR offshore) oil',
        "keywords": r"hurricane|tropical storm|gulf of mexico|gulf coast",
        "color": "#008300",
        "months": [6, 7, 8, 9, 10, 11],   # Atlantic hurricane season (Jun-Nov)
    },
    "demand": {
        "label": "Oil demand & recession fears",
        "query": '(recession OR slowdown OR "demand outlook") ("oil demand" OR "crude demand")',
        "keywords": r"demand|recession|slowdown|china.*(import|economy)",
        "color": "#6250d6",
    },
    "spr": {
        "label": "Strategic reserve releases",
        "query": '("Strategic Petroleum Reserve" OR "emergency oil stocks" OR "IEA release")',
        "keywords": r"strategic petroleum reserve|\bspr\b|emergency (oil )?stock|iea release",
        "color": "#e34948",
    },
}



# ---------------------------------------------------------------------------
# A polite GDELT client: GDELT allows one request every 5 seconds
# ---------------------------------------------------------------------------
_last_request = [0.0]


def gdelt(params: dict, tries: int = 3, spacing: float = 6, timeout: float = 120,
          backoff: float = 45) -> dict:
    """Call GDELT politely, waiting out its rate limits. Only the daily
    GitHub job calls this; the website never asks GDELT anything live."""
    for attempt in range(tries):
        wait = spacing - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        response = requests.get(GDELT_URL, params={**params, "format": "json"}, timeout=timeout)
        _last_request[0] = time.time()
        if response.status_code == 429:      # too many requests: back off
            if attempt < tries - 1:
                time.sleep(backoff * (attempt + 1))
            continue
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            # Empty body = no results. Any text = GDELT explaining a problem with
            # the search (e.g. a disallowed character) - show it so it gets fixed.
            if response.text.strip():
                print(f"  GDELT said: {response.text.strip()[:200]}")
            return {}
    raise RuntimeError("GDELT is busy (rate limit). Please try again in a minute.")


def timeline(query: str, start: str = HISTORY_START, spacing: float = 6) -> pd.DataFrame:
    """Daily article counts for a query, plus all articles GDELT saw that day."""
    params = {"query": query, "mode": "timelinevolraw", "startdatetime": start,
              "enddatetime": pd.Timestamp.now(tz="UTC").strftime("%Y%m%d%H%M%S")}
    data = gdelt(params, spacing=spacing)
    points = (data.get("timeline") or [{}])[0].get("data", [])
    table = pd.DataFrame(points, columns=["date", "value", "norm"])
    table["date"] = pd.to_datetime(table["date"].str[:8])
    return table.rename(columns={"value": "articles", "norm": "all_articles"})


# ---------------------------------------------------------------------------
# History and spikes
# ---------------------------------------------------------------------------
def update(searches: dict | None = None, path: Path = TIMELINES_PATH) -> bool:
    """Bring every search's coverage history up to date (run daily).
    searches: {key: (label, query)}; defaults to the news TOPICS.

    Searches already saved only fetch the last 3 weeks (recent days get revised
    as GDELT finishes counting); new ones fetch the full history. Progress is
    saved after each one, so an interrupted run resumes where it stopped.
    If GDELT refuses one search (rate limit), we move on to the next; the job
    runs every 3 hours, so a refused search is retried soon.
    Returns False if any search was refused."""
    if searches is None:
        searches = {k: (t["label"], t["query"]) for k, t in TOPICS.items()}
    path.parent.mkdir(exist_ok=True)
    table = load_timelines(path)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    last_saved = table.groupby("topic")["date"].max()
    # Missing searches first (they matter most), then ones not refreshed today
    missing = [k for k in searches if k not in last_saved]
    stale = [k for k in searches if k in last_saved and last_saved[k] < today]
    all_ok = True
    for key in missing + stale:
        label, query = searches[key]
        if key in missing:
            start, kind = HISTORY_START, "full history"
        else:
            start, kind = (last_saved[key] - pd.Timedelta(days=21)).strftime("%Y%m%d000000"), "recent days"
        print(f"Fetching {kind}: {label}...")
        try:
            fresh = timeline(query, start=start, spacing=10)
        except (RuntimeError, requests.RequestException) as error:
            print(f"  Skipped for now ({error}); the next run will try again.")
            all_ok = False
            continue
        if fresh.empty:
            print("  (no data returned - keeping what we had)")
            continue
        fresh.insert(0, "topic", key)
        keep = table[~((table["topic"] == key) & (table["date"] >= fresh["date"].min()))]
        table = pd.concat([keep, fresh], ignore_index=True).sort_values(["topic", "date"])
        table.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"Saved {len(table):,} rows to {path}"
          + ("" if all_ok else " (some searches were refused and will be retried)"))
    return all_ok


def load_worldwide() -> pd.DataFrame:
    """Daily topic coverage in worldwide news: Media Cloud (since 2015), or the
    old GDELT file if the Media Cloud one isn't there."""
    import mediacloud_news
    table = mediacloud_news.load()
    return table if not table.empty else load_timelines()


def load_timelines(path: Path = TIMELINES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame({"topic": pd.Series(dtype=str), "date": pd.Series(dtype="datetime64[ns]"),
                             "articles": pd.Series(dtype=float), "all_articles": pd.Series(dtype=float)})
    return pd.read_csv(path, parse_dates=["date"])


# Spike settings per news source. GDELT counts thousands of articles a day;
# the market news archive (market_news.py) only a few dozen, so it needs a
# lower article minimum and an average (not median) baseline - a median of
# mostly-zero days would be zero.
SOURCES = {
    # Worldwide news (Media Cloud; GDELT only as a fallback). Media Cloud counts
    # fewer stories per topic than GDELT did, so a spike needs 10 stories, not 20.
    "world": {"min_articles": 10, "baseline": "median", "skip_outages": True},
    "market": {"min_articles": 4, "baseline": "mean", "skip_outages": False},
}


def coverage(t: pd.DataFrame, source: str = "world") -> pd.DataFrame:
    """Add each day's share of all news, the 'normal' share and the ratio."""
    settings = SOURCES[source]
    t = t.sort_values("date").copy()
    # Drop today's partial day: it's still being collected
    t = t[t["date"] < pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()]
    collected_ok = t["all_articles"] > 0
    if settings["skip_outages"]:
        # Skip days when GDELT itself collected far fewer articles than usual
        # (an outage): a topic's share of a tiny total looks like a fake spike.
        typical_total = t["all_articles"].shift(1).rolling(30, min_periods=10).median()
        collected_ok &= ~(t["all_articles"] < 0.5 * typical_total)
    t["share_per_million"] = (t["articles"] / t["all_articles"] * 1e6).where(collected_ok)
    past = t["share_per_million"].shift(1).rolling(BASELINE_DAYS, min_periods=30)
    t["normal"] = past.median() if settings["baseline"] == "median" else past.mean()
    t["ratio"] = t["share_per_million"] / t["normal"].where(t["normal"] > 0)
    return t


def find_spikes(t: pd.DataFrame, category: str = "topic", source: str = "world",
                min_articles: int | None = None) -> pd.DataFrame:
    """One event per news spike, in the same shape as the other event studies.

    The event date is set ONE business day before the spike day, so the
    starting price is from before the story broke even if it broke the
    previous evening (news is dated in UTC; markets are not)."""
    if min_articles is None:
        min_articles = SOURCES[source]["min_articles"]
    c = coverage(t, source)
    # A spike must also be a busy day by the topic's own standards: in the top
    # 10% of its daily article counts over the previous 12 months. This stops
    # usually-quiet topics "spiking" on a handful of articles.
    busy_day = c["articles"].shift(1).rolling(365, min_periods=90).quantile(0.90)
    hot = c[(c["ratio"] >= SPIKE_RATIO) & (c["articles"] >= min_articles)
            & ~(c["articles"] < busy_day)]
    topic = t["topic"].iloc[0] if "topic" in t and len(t) else None
    months = TOPICS.get(topic, {}).get("months")
    if months:   # seasonal topics (hurricanes) only count in season
        hot = hot[hot["date"].dt.month.isin(months)]
    rows, last = [], None
    for _, day in hot.iterrows():
        if last is not None and (day["date"] - last).days < COOLDOWN_DAYS:
            continue
        last = day["date"]
        rows.append({
            "date": day["date"] - pd.offsets.BDay(1),
            "spike_day": day["date"],
            category: t["topic"].iloc[0] if "topic" in t else category,
            "ratio": round(day["ratio"], 1),
            "articles": int(day["articles"]),
            "description": f"Coverage {day['ratio']:.1f}x normal ({int(day['articles']):,} articles)",
        })
    return pd.DataFrame(rows, columns=["date", "spike_day", category, "ratio",
                                       "articles", "description"])


def all_spikes(timelines: pd.DataFrame, source: str = "world") -> pd.DataFrame:
    parts = [find_spikes(group, source=source) for _, group in timelines.groupby("topic")]
    if not parts:
        return find_spikes(timelines.assign(topic="none")).iloc[0:0]
    return pd.concat(parts, ignore_index=True).sort_values("date").reset_index(drop=True)


def current_heat(timelines: pd.DataFrame, source: str = "world") -> pd.DataFrame:
    """For each topic: coverage over the last 3 days vs normal."""
    rows = []
    for key, group in timelines.groupby("topic"):
        c = coverage(group, source)
        if c.empty:
            continue
        # The last 3 usable days within the past week (days skipped as GDELT
        # collection outages don't count, so one bad day can't hide a topic)
        usable = c[c["share_per_million"].notna()]
        recent = usable[usable["date"] >= c["date"].iloc[-1] - pd.Timedelta(days=7)].tail(3)
        if recent.empty:
            continue
        normal = c["normal"].iloc[-1]
        ratio = recent["share_per_million"].mean() / normal if normal else float("nan")
        if pd.isna(ratio):          # not enough history to say what's normal
            continue
        articles = int(recent["articles"].sum())
        rows.append({"topic": key, "label": TOPICS[key]["label"], "heat": ratio,
                     "articles_3d": articles,
                     # too few articles for the ratio to mean anything (one
                     # story on a quiet day can look like "6x normal")
                     "enough": articles >= SOURCES[source]["min_articles"],
                     "last_day": c["date"].iloc[-1]})
    columns = ["topic", "label", "heat", "articles_3d", "enough", "last_day"]
    return pd.DataFrame(rows, columns=columns).sort_values(["enough", "heat"],
                                                           ascending=[False, False])


def heat_now(timelines: pd.DataFrame, market_timelines: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Topic heat from worldwide news, or from market news if the worldwide
    data is more than a few days old (e.g. GDELT blocked the daily update).
    Returns (heat, source). Used by the website and by the alerts job."""
    heat = current_heat(timelines)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    if not heat.empty and heat["last_day"].max() >= today - pd.Timedelta(days=4):
        return heat, "world"
    market = current_heat(market_timelines, "market")
    return (market, "market") if not market.empty else (heat, "world")


# ---------------------------------------------------------------------------
# Headline tagging (used for the market news archive)
# ---------------------------------------------------------------------------
def classify(title: str) -> list[str]:
    title = title.lower()
    return [key for key, t in TOPICS.items() if re.search(t["keywords"], title)]


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "update"
    if command == "update":
        update()


if __name__ == "__main__":
    main()
