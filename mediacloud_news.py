"""
Worldwide news coverage from Media Cloud (mediacloud.org), an open archive of
online news run by universities. For each news topic we save how many stories
matched its search each day, and how many stories were collected in total,
in news_data/mc_timelines.csv. That's the same shape as the old GDELT file,
so spikes, "normal coverage" and the topic cards work the same way.

Why Media Cloud instead of GDELT: history back to 2015 with every day present,
steady daily totals, and our own API key (GDELT rate-limits everyone sharing
GitHub's servers, and its collection dropped sharply in late 2026).

Only counts are used and shown (Media Cloud's terms allow reusing counts and
charts; story titles belong to the publishers).

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

PATH = Path(__file__).parent / "news_data" / "mc_timelines.csv"
HISTORY_START = dt.date(2015, 1, 1)
# "Global English Language Sources" (about 1,600 sites) + "United States - National"
COLLECTIONS = [9272347, 34412234]
REFETCH_DAYS = 21          # recent days are revised as more stories are collected
WAIT_SECONDS = 31          # some Media Cloud endpoints allow 2 requests a minute


def api_key() -> str | None:
    key = os.environ.get("MEDIACLOUD_API_KEY")
    if not key:
        try:
            from dotenv import dotenv_values
            key = dotenv_values(Path(__file__).parent / ".env").get("MEDIACLOUD_API_KEY")
        except ImportError:
            pass
    return key


def to_mediacloud(query: str) -> str:
    """Our topic searches put groups side by side to mean "and" (GDELT style);
    Media Cloud needs the AND written out."""
    parts = re.findall(r'\([^)]*\)|"[^"]*"|\S+', query)
    return " AND ".join(parts)


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


def load(path: Path = PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["topic", "date", "articles", "all_articles"])
    return pd.read_csv(path, parse_dates=["date"])


def update(path: Path = PATH) -> bool:
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
    for key_, topic in news.TOPICS.items():
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
    if (sys.argv[1] if len(sys.argv) > 1 else "update") == "update":
        sys.exit(0 if update() else 1)
