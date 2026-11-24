"""
Worldwide news coverage from Media Cloud (mediacloud.org), an open archive of
online news run by universities. For each news topic we save how many stories
matched its search each day, and how many stories were collected in total,
in news_data/mc_timelines.csv. That's the same shape as the old GDELT file,
so spikes, "normal coverage" and the topic cards work the same way.

Why Media Cloud instead of GDELT: history back to 2015 with every day present,
steady daily totals, and our own API key (GDELT rate-limits everyone sharing
GitHub's servers, and its collection dropped sharply in late 2026).

Mostly counts are used (Media Cloud's terms allow reusing counts and charts).
Story headlines are shown only as links to the publishers' own pages: the
latest stories behind a topic card (mc_stories.csv), and the biggest stories
on each news spike day (mc_spike_stories.csv, shown when a dot is clicked).

Run by .github/workflows/news.yml every 3 hours:
    python mediacloud_news.py update
Needs MEDIACLOUD_API_KEY (in .env locally, a GitHub secret in Actions).
"""

import datetime as dt
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

import news
import credentials

PATH = Path(__file__).parent / "news_data" / "mc_timelines.csv"
GAS_PATH = Path(__file__).parent / "news_data" / "mc_gas_timelines.csv"   # natural gas topics
GOLD_PATH = Path(__file__).parent / "news_data" / "mc_gold_timelines.csv"  # gold topics
HISTORY_START = dt.date(2015, 1, 1)
# "Global English Language Sources" (about 1,600 sites) + "United States - National"
COLLECTIONS = [9272347, 34412234]
REFETCH_DAYS = 21          # recent days are revised as more stories are collected
WAIT_SECONDS = 31          # some Media Cloud endpoints allow 2 requests a minute


def api_key() -> str | None:
    credentials.load(("MEDIACLOUD_API_KEY",))
    return os.environ.get("MEDIACLOUD_API_KEY")


def to_mediacloud(query: str) -> str:
    """Our topic searches put groups side by side to mean "and" (GDELT style);
    Media Cloud needs the AND written out."""
    parts = re.findall(r'\([^)]*\)|"[^"]*"|\S+', query)
    words = ("AND", "OR", "NOT")
    out = []
    for part in parts:          # (no AND around an OR someone typed)
        if out and part.upper() not in words and out[-1].upper() not in words:
            out.append("AND")
        out.append(part.upper() if part.upper() in words else part)
    return " ".join(out)


def counts(search, query: str, start: dt.date, end: dt.date, tries: int = 3) -> pd.DataFrame:
    """Daily counts for one search. Media Cloud sometimes drops a long answer
    halfway, so a failed request is retried (after a pause) a couple of times."""
    for attempt in range(tries):
        try:
            rows = search.story_count_over_time(to_mediacloud(query), start, end,
                                                collection_ids=COLLECTIONS)
            break
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(WAIT_SECONDS)
    t = pd.DataFrame(rows, columns=["date", "count", "total_count", "ratio"])
    t["date"] = pd.to_datetime(t["date"])
    return t.rename(columns={"count": "articles", "total_count": "all_articles"})[
        ["date", "articles", "all_articles"]]


STORIES_PATH = Path(__file__).parent / "news_data" / "mc_stories.csv"
STORY_DAYS = 3             # the same window as the topic cards
STORY_PAGES = 3            # at most 3 pages of 200 stories per topic


def _title_key(title: str) -> str:
    """Same headline, any punctuation or site: one story (syndicated copies
    of one article appear on dozens of sites)."""
    return re.sub(r"[^a-z0-9 ]", "", str(title).lower())[:70]


def topic_stories(search, key_: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """The articles behind one topic's count: copies removed, and only those
    whose headline is about the topic (Media Cloud searches the full text, so
    a page that mentions OPEC in a sidebar counts too)."""
    query, rows, token = to_mediacloud(news.TOPICS[key_]["query"]), [], None
    for _ in range(STORY_PAGES):
        page, token = search.story_list(query, start, end, collection_ids=COLLECTIONS,
                                        page_size=200, pagination_token=token)
        rows += page
        if not token:
            break
        time.sleep(WAIT_SECONDS)
    columns = ["topic", "time", "headline", "url", "source", "copies"]
    capped = bool(token)          # more pages left: the count is a lower bound
    if not rows:
        return pd.DataFrame(columns=columns)
    t = pd.DataFrame(rows)
    t = t[t["title"].map(lambda title: key_ in news.classify(str(title)))]
    if t.empty:
        out = pd.DataFrame(columns=columns)
        out.attrs["capped"] = capped
        return out
    t["key"] = t["title"].map(_title_key)
    t["copies"] = t.groupby("key")["key"].transform("size")
    t = t.sort_values("publish_date").drop_duplicates("key")      # the first to publish it
    out = pd.DataFrame({"topic": key_, "time": pd.to_datetime(t["publish_date"]),
                        "headline": t["title"], "url": t["url"], "source": t["media_name"],
                        "copies": t["copies"]})[columns]
    out.attrs["capped"] = capped
    return out


def update_stories(path: Path = STORIES_PATH) -> bool:
    """Save the latest articles behind every topic's count (shown when a
    topic card on the site is clicked). Replaces the file each run."""
    import mediacloud.api as mc
    key = api_key()
    if not key:
        print("No MEDIACLOUD_API_KEY set - skipping.")
        return False
    search = mc.SearchApi(key)
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=STORY_DAYS)
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["topic"])
    tables, counts, all_ok = [], [], True
    for i, key_ in enumerate(news.TOPICS):
        if i:
            time.sleep(WAIT_SECONDS)
        try:
            found = topic_stories(search, key_, start, end)
            print(f"{news.TOPICS[key_]['label']}: {len(found)} stories")
            counts.append({"topic": key_, "distinct": len(found),
                           "capped": found.attrs.get("capped", False),
                           "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        except Exception as error:
            print(f"{key_}: skipped for now ({error!r}); keeping the last saved list.")
            found, all_ok = old[old["topic"] == key_], False
        tables.append(found)
    path.parent.mkdir(exist_ok=True)
    pd.concat(tables, ignore_index=True).to_csv(path, index=False)
    # Distinct-story counts for the topic cards (topics that failed this run
    # are left out, so their cards fall back to the plain count)
    pd.DataFrame(counts, columns=["topic", "distinct", "capped", "updated"]).to_csv(
        news.STORY_COUNTS_PATH, index=False)
    return all_ok


SPIKE_STORIES_PATH = Path(__file__).parent / "news_data" / "mc_spike_stories.csv"
SPIKE_COLUMNS = ["market", "topic", "spike_day", "rank", "headline", "url", "source", "copies", "on_topic"]
SPIKE_TOP = 8              # stories saved per spike
# Each market's topics and coverage file ("oil" is the oil site's news.TOPICS)
MARKET_TOPICS = {"oil": (PATH, news.TOPICS), "gas": (GAS_PATH, news.GAS_TOPICS),
                 "gold": (GOLD_PATH, news.GOLD_TOPICS)}


def _patiently(call, tries: int = 3):
    """Run one Media Cloud request, waiting and retrying if it says 'rate limited'."""
    for attempt in range(tries):
        try:
            return call()
        except Exception as error:
            if attempt == tries - 1 or "429" not in str(error):
                raise
            time.sleep(WAIT_SECONDS * 2)


def day_stories(search, query: str, day: dt.date, keywords: str | None = None,
                top: int = SPIKE_TOP) -> pd.DataFrame:
    """The biggest stories on one day for a search: copies of the same article
    on many sites merged, ranked by how many sites ran it. Stories whose
    headline is about the topic (`keywords`) come first, since Media Cloud
    also counts pages that only mention it in passing. One request (about
    30 seconds: Media Cloud is slow at listing stories)."""
    rows, _ = _patiently(lambda: search.story_list(to_mediacloud(query), day, day,
                                                   collection_ids=COLLECTIONS, page_size=200))
    columns = ["headline", "url", "source", "copies", "on_topic"]
    if not rows:
        return pd.DataFrame(columns=columns)
    t = pd.DataFrame(rows)
    t["key"] = t["title"].map(_title_key)
    t["copies"] = t.groupby("key")["key"].transform("size")
    t = t.sort_values("publish_date").drop_duplicates("key")      # the first to publish it
    t["on_topic"] = (t["title"].fillna("").str.lower().str.contains(keywords, regex=True)
                     if keywords else True)
    t = t.sort_values(["on_topic", "copies"], ascending=False).head(top)
    return pd.DataFrame({"headline": t["title"], "url": t["url"], "source": t["media_name"],
                         "copies": t["copies"], "on_topic": t["on_topic"]})[columns]


def load_spike_stories(path: Path = SPIKE_STORIES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=SPIKE_COLUMNS)
    return pd.read_csv(path, parse_dates=["spike_day"])


def update_spike_stories(minutes: float = 10, path: Path = SPIKE_STORIES_PATH) -> bool:
    """Save the biggest stories on each news spike day, for every market's
    topics (shown when a spike's dot is clicked on the site). Newest spikes
    first; a spike already saved is never fetched again. Stops after
    `minutes` and carries on next run, since each spike takes ~30 seconds.
    A spike with no stories is saved as one empty row so it isn't retried."""
    import mediacloud.api as mc
    key = api_key()
    if not key:
        print("No MEDIACLOUD_API_KEY set - skipping.")
        return False
    search = mc.SearchApi(key)
    saved = load_spike_stories(path)
    done = set(zip(saved["market"], saved["topic"],
                   pd.to_datetime(saved["spike_day"]).dt.strftime("%Y-%m-%d")))
    today = dt.datetime.now(dt.timezone.utc).date()
    todo = []
    for market, (timelines_path, topics) in MARKET_TOPICS.items():
        timelines = load(timelines_path)
        if timelines.empty:
            continue
        for _, s in news.all_spikes(timelines).iterrows():
            day = s["spike_day"].date()
            if day < today and (market, s["topic"], f"{day:%Y-%m-%d}") not in done:
                todo.append((day, market, s["topic"], topics[s["topic"]]))
    todo.sort(key=lambda item: item[0], reverse=True)
    print(f"{len(todo)} spikes still to fetch")
    stop_at, fresh, all_ok = time.time() + minutes * 60, [], True

    def save() -> None:
        if fresh:
            path.parent.mkdir(exist_ok=True)
            table = pd.concat([saved, *fresh], ignore_index=True)
            table.sort_values(["market", "topic", "spike_day", "rank"]).to_csv(
                path, index=False, date_format="%Y-%m-%d")

    for i, (day, market, topic, info) in enumerate(todo):
        if time.time() > stop_at:
            print(f"Out of time; {len(todo) - i} spikes left for next run.")
            break
        try:
            found = day_stories(search, info["query"], day, info.get("keywords"))
        except Exception as error:
            print(f"{market} {topic} {day}: skipped for now ({error!r})")
            all_ok = False
            time.sleep(WAIT_SECONDS)
            continue
        if found.empty:
            found = pd.DataFrame([{"headline": "", "url": "", "source": "", "copies": 0, "on_topic": False}])
        fresh.append(found.assign(market=market, topic=topic, spike_day=pd.Timestamp(day),
                                  rank=range(1, len(found) + 1))[SPIKE_COLUMNS])
        print(f"{market} {topic} {day}: {len(found)} stories")
        if len(fresh) % 5 == 0:
            save()
    save()
    return all_ok


def load_stories(path: Path = STORIES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["topic", "time", "headline", "url", "source", "copies"])
    return pd.read_csv(path, parse_dates=["time"])


def load(path: Path = PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["topic", "date", "articles", "all_articles"])
    return pd.read_csv(path, parse_dates=["date"])


def update(path: Path = PATH, topics: dict | None = None) -> bool:
    """Bring every topic up to date. New topics get their full history; others
    re-fetch the last few weeks. Progress is saved after each topic, and a
    topic that fails is simply retried on the next run. False if any failed."""
    import mediacloud.api as mc
    key = api_key()
    if not key:
        print("No MEDIACLOUD_API_KEY set - skipping.")
        return False
    search = mc.SearchApi(key)
    table = load(path)
    today = dt.datetime.now(dt.timezone.utc).date()
    last = table.groupby("topic")["date"].max()
    all_ok, first = True, True
    for key_, topic in (topics or news.TOPICS).items():
        if key_ in last and last[key_].date() >= today:
            continue                                 # already up to date today
        start = (HISTORY_START if key_ not in last
                 else last[key_].date() - dt.timedelta(days=REFETCH_DAYS))
        if not first:
            time.sleep(WAIT_SECONDS)
        first = False
        print(f"Fetching {topic['label']} from {start}...")
        try:
            fresh = counts(search, topic["query"], start, today)
        except Exception as error:
            print(f"  Skipped for now ({error!r}); the next run will try again.")
            all_ok = False
            continue
        if fresh.empty:
            print("  (no data returned - keeping what we had)")
            continue
        fresh.insert(0, "topic", key_)
        keep = table[~((table["topic"] == key_) & (table["date"] >= fresh["date"].min()))]
        table = pd.concat([keep, fresh], ignore_index=True).sort_values(["topic", "date"])
        path.parent.mkdir(exist_ok=True)
        table.to_csv(path, index=False, date_format="%Y-%m-%d")
        print(f"  {len(fresh):,} days, {int(fresh['articles'].sum()):,} matching stories")
    return all_ok


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "update"
    if command == "update":
        sys.exit(0 if update() else 1)
    if command == "update-gas":          # the natural gas topics
        sys.exit(0 if update(GAS_PATH, news.GAS_TOPICS) else 1)
    if command == "update-gold":         # the gold topics
        sys.exit(0 if update(GOLD_PATH, news.GOLD_TOPICS) else 1)
    if command == "stories":
        sys.exit(0 if update_stories() else 1)
    if command == "spike-stories":       # the biggest stories on each spike day
        minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 10
        sys.exit(0 if update_spike_stories(minutes) else 1)
