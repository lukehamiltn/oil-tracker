"""
News: match today's oil news to similar moments in the past, and show what
the oil market did next.

Source: the GDELT Project (gdeltproject.org), a free database that monitors
news worldwide. Two things come from it:
  1. HISTORY - for each news TOPIC (e.g. "attacks on tankers"), how much of
     the world's news coverage it got every day since 2017.
  2. TODAY - the latest oil-related headlines, each tagged with its topic.

A "news spike" is a day when a topic suddenly got far more coverage than
usual (at least 3x its normal share of all news). Each spike is treated as
an event, and we measure how Brent moved afterwards - just like the OPEC+,
EIA and Fed event studies.

The history is refreshed once a day by a GitHub Action
(.github/workflows/news.yml), which saves it to news_data/timelines.csv, so
the website loads it instantly instead of querying GDELT on every visit.

Run it with:
    python news.py update           refresh the history file (slow: GDELT rate limits)
    python news.py save-headlines   save the latest headlines (website backup)
    python news.py headlines        show the latest tagged headlines
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
HEADLINE_QUERY = "(oil OR crude OR OPEC OR Brent) sourcelang:english"


# ---------------------------------------------------------------------------
# A polite GDELT client: GDELT allows one request every 5 seconds
# ---------------------------------------------------------------------------
_last_request = [0.0]


def gdelt(params: dict, tries: int = 5, spacing: float = 6, timeout: float = 120,
          backoff: float = 30) -> dict:
    """Call GDELT politely. Background jobs use the patient defaults; the
    website uses quick=True settings so a busy GDELT never stalls the page."""
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


def timeline(query: str, start: str = HISTORY_START, spacing: float = 6,
             quick: bool = False) -> pd.DataFrame:
    """Daily article counts for a query, plus all articles GDELT saw that day."""
    params = {"query": query, "mode": "timelinevolraw", "startdatetime": start,
              "enddatetime": pd.Timestamp.now(tz="UTC").strftime("%Y%m%d%H%M%S")}
    data = (gdelt(params, tries=2, spacing=0, timeout=30, backoff=6) if quick
            else gdelt(params, spacing=spacing))
    points = (data.get("timeline") or [{}])[0].get("data", [])
    table = pd.DataFrame(points, columns=["date", "value", "norm"])
    table["date"] = pd.to_datetime(table["date"].str[:8])
    return table.rename(columns={"value": "articles", "norm": "all_articles"})


# ---------------------------------------------------------------------------
# History and spikes
# ---------------------------------------------------------------------------
def update() -> None:
    """Bring every topic's coverage history up to date (run daily).

    Topics already saved only fetch the last 3 weeks (recent days get revised
    as GDELT finishes counting); new topics fetch the full history. Progress is
    saved after each topic, so an interrupted run resumes where it stopped."""
    TIMELINES_PATH.parent.mkdir(exist_ok=True)
    table = load_timelines()
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    last_saved = table.groupby("topic")["date"].max()
    # Missing topics first (they matter most), then topics not refreshed today
    missing = [k for k in TOPICS if k not in last_saved]
    stale = [k for k in TOPICS if k in last_saved and last_saved[k] < today]
    for key in missing + stale:
        topic = TOPICS[key]
        if key in missing:
            start, kind = HISTORY_START, "full history"
        else:
            start, kind = (last_saved[key] - pd.Timedelta(days=21)).strftime("%Y%m%d000000"), "recent days"
        print(f"Fetching {kind}: {topic['label']}...")
        try:
            fresh = timeline(topic["query"], start=start, spacing=10)
        except RuntimeError as error:
            print(f"  {error} Stopping here; progress so far is saved.")
            break
        if fresh.empty:
            print("  (no data returned - keeping what we had)")
            continue
        fresh.insert(0, "topic", key)
        keep = table[~((table["topic"] == key) & (table["date"] >= fresh["date"].min()))]
        table = pd.concat([keep, fresh], ignore_index=True).sort_values(["topic", "date"])
        table.to_csv(TIMELINES_PATH, index=False, date_format="%Y-%m-%d")
    print(f"Saved {len(table):,} rows to {TIMELINES_PATH}")


def load_timelines() -> pd.DataFrame:
    if not TIMELINES_PATH.exists():
        return pd.DataFrame({"topic": pd.Series(dtype=str), "date": pd.Series(dtype="datetime64[ns]"),
                             "articles": pd.Series(dtype=float), "all_articles": pd.Series(dtype=float)})
    return pd.read_csv(TIMELINES_PATH, parse_dates=["date"])


def coverage(t: pd.DataFrame) -> pd.DataFrame:
    """Add each day's share of all news, the 'normal' share and the ratio."""
    t = t.sort_values("date").copy()
    # Drop today's partial day: GDELT is still collecting it
    t = t[t["date"] < pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()]
    # Skip days when GDELT itself collected far fewer articles than usual (an
    # outage): a topic's share of a tiny total looks like a fake spike.
    typical_total = t["all_articles"].shift(1).rolling(30, min_periods=10).median()
    collected_ok = (t["all_articles"] > 0) & ~(t["all_articles"] < 0.5 * typical_total)
    t["share_per_million"] = (t["articles"] / t["all_articles"] * 1e6).where(collected_ok)
    t["normal"] = t["share_per_million"].shift(1).rolling(BASELINE_DAYS, min_periods=30).median()
    t["ratio"] = t["share_per_million"] / t["normal"].where(t["normal"] > 0)
    return t


def find_spikes(t: pd.DataFrame, category: str = "topic") -> pd.DataFrame:
    """One event per news spike, in the same shape as the other event studies.

    The event date is set ONE business day before the spike day, so the
    starting price is from before the story broke even if it broke the
    previous evening (news is dated in UTC; markets are not)."""
    c = coverage(t)
    hot = c[(c["ratio"] >= SPIKE_RATIO) & (c["articles"] >= MIN_ARTICLES)]
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


def all_spikes(timelines: pd.DataFrame) -> pd.DataFrame:
    parts = [find_spikes(group) for _, group in timelines.groupby("topic")]
    if not parts:
        return find_spikes(timelines.assign(topic="none")).iloc[0:0]
    return pd.concat(parts, ignore_index=True).sort_values("date").reset_index(drop=True)


def current_heat(timelines: pd.DataFrame) -> pd.DataFrame:
    """For each topic: coverage over the last 3 days vs normal."""
    rows = []
    for key, group in timelines.groupby("topic"):
        c = coverage(group)
        recent = c.tail(3)
        normal = c["normal"].iloc[-1]
        ratio = recent["share_per_million"].mean() / normal if normal else float("nan")
        rows.append({"topic": key, "label": TOPICS[key]["label"], "heat": ratio,
                     "articles_3d": int(recent["articles"].sum()),
                     "last_day": c["date"].iloc[-1]})
    columns = ["topic", "label", "heat", "articles_3d", "last_day"]
    return pd.DataFrame(rows, columns=columns).sort_values("heat", ascending=False)


# ---------------------------------------------------------------------------
# Today's headlines
# ---------------------------------------------------------------------------
def classify(title: str) -> list[str]:
    title = title.lower()
    return [key for key, t in TOPICS.items() if re.search(t["keywords"], title)]


HEADLINES_PATH = TIMELINES_PATH.parent / "headlines.csv"
HEADLINE_COLUMNS = ["time", "title", "source", "url", "topics"]


def headlines(hours: int = 24, limit: int = 75, quick: bool = False) -> pd.DataFrame:
    """Latest oil headlines. quick=True makes ONE short attempt (for the
    website); otherwise it waits out GDELT's rate limits (for background jobs)."""
    params = {"query": HEADLINE_QUERY, "mode": "artlist", "maxrecords": limit,
              "timespan": f"{hours}h", "sort": "datedesc"}
    data = (gdelt(params, tries=1, spacing=0, timeout=10) if quick
            else gdelt(params))
    articles = pd.DataFrame(data.get("articles", []))
    if articles.empty:
        return pd.DataFrame(columns=HEADLINE_COLUMNS)
    articles = articles.drop_duplicates("title")
    articles["time"] = pd.to_datetime(articles["seendate"], format="%Y%m%dT%H%M%SZ", utc=True)
    articles["topics"] = articles["title"].apply(classify)
    return articles.rename(columns={"domain": "source"})[HEADLINE_COLUMNS]


def save_headlines() -> None:
    """Save the latest headlines as a backup the website can always show."""
    heads = headlines(hours=48)
    if heads.empty:
        print("No headlines returned - keeping the saved ones.")
        return
    HEADLINES_PATH.parent.mkdir(exist_ok=True)
    heads.assign(topics=heads["topics"].str.join("|")).to_csv(HEADLINES_PATH, index=False)
    print(f"Saved {len(heads)} headlines to {HEADLINES_PATH}")


def load_saved_headlines() -> pd.DataFrame:
    if not HEADLINES_PATH.exists():
        return pd.DataFrame(columns=HEADLINE_COLUMNS)
    saved = pd.read_csv(HEADLINES_PATH, keep_default_na=False)
    saved["time"] = pd.to_datetime(saved["time"], utc=True, format="ISO8601")
    saved["topics"] = saved["topics"].apply(lambda s: [t for t in s.split("|") if t in TOPICS])
    return saved[HEADLINE_COLUMNS]


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "update"
    if command == "update":
        update()
    elif command == "save-headlines":
        save_headlines()
    elif command == "headlines":
        for _, h in headlines().iterrows():
            print(f"{h['time']:%H:%M} {h['source']:25} {', '.join(h['topics']) or '-':20} {h['title'][:90]}")


if __name__ == "__main__":
    main()
