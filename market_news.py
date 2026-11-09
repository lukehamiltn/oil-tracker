"""
Market news: an archive of oil-related financial news since 2015, from
Alpaca's news feed (mostly Benzinga). It uses the same Alpaca keys as the bots.

Why this exists alongside GDELT (news.py): GDELT covers the whole world's
news but rate-limits hard, so the website can't ask it anything live. Alpaca
allows 200 requests a minute on our own keys, and its archive is small
enough (~5-40 oil articles a day) to save in full. That makes the website's
search instant and lets every past news spike show what the headlines said.

Stories are found through oil-related tickers (oil funds, oil majors and
oil-service firms), then tagged by topic using the headline keywords from
news.TOPICS.

The archive lives in news_data/market_news/, one CSV per month. A GitHub
Action refreshes the current month every few hours.

Run it with:
    python market_news.py update     download missing months + refresh this month
    python market_news.py latest     show the latest oil headlines
"""

import html
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

import news

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
ARCHIVE_DIR = Path(__file__).parent / "news_data" / "market_news"
ARCHIVE_START = pd.Timestamp("2015-01-01")
MARKET_TZ = "America/New_York"     # news is dated by the New York trading day

# Tickers whose news we collect: oil funds, majors, producers, services, refiners
SYMBOLS = ["USO", "BNO", "UCO", "SCO", "XLE", "XOP", "OIH", "XOM", "CVX", "COP",
           "OXY", "BP", "SHEL", "SLB", "HAL", "MPC", "VLO", "PSX"]
COLUMNS = ["time", "headline", "summary", "source", "url", "topics"]

# Words that make a headline about oil (used to drop e.g. "Exxon stock split" noise
# from the headline list; topic-tagged headlines are always kept)
OIL_WORDS = (r"\boil|crude|opec|brent|\bwti\b|barrel|gasoline|diesel|refin|pipeline|"
             r"tanker|rig count|petroleum|\blng\b|natural gas|fuel|hormuz|drilling|shale")


# ---------------------------------------------------------------------------
# Talking to Alpaca
# ---------------------------------------------------------------------------
def _headers() -> dict:
    """Alpaca keys: from the environment (GitHub), .env (local) or Streamlit secrets."""
    if "ALPACA_API_KEY" not in os.environ:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    if "ALPACA_API_KEY" not in os.environ:
        try:
            import streamlit as st
            for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
                os.environ.setdefault(name, st.secrets[name])
        except Exception:
            pass
    return {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = text.replace("\ufffd", "'")      # broken apostrophes in the source data
    return " ".join(text.split())[:limit]


def fetch(start: pd.Timestamp, end: pd.Timestamp, timeout: float = 30,
          max_pages: int | None = None, waits: int = 3) -> pd.DataFrame:
    """All articles for our tickers between start and end (UTC timestamps).
    If Alpaca says "too many requests", wait 20s and retry, at most `waits`
    times (the website passes 0, so it never waits)."""
    headers, rows, token, pages = _headers(), [], None, 0
    while True:
        params = {"symbols": ",".join(SYMBOLS), "limit": 50, "sort": "desc",
                  "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if token:
            params["page_token"] = token
        response = requests.get(NEWS_URL, headers=headers, params=params, timeout=timeout)
        if response.status_code == 429 and waits > 0:   # over 200 a minute
            waits -= 1
            time.sleep(20)
            continue
        response.raise_for_status()
        data = response.json()
        rows += data.get("news", [])
        token, pages = data.get("next_page_token"), pages + 1
        if not token or (max_pages and pages >= max_pages):
            break
        time.sleep(0.35)                        # stay well under the limit
    return to_table(rows)


def to_table(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    t = pd.DataFrame(rows)
    t["time"] = pd.to_datetime(t["created_at"], utc=True)
    t["headline"] = t["headline"].map(lambda s: _clean(s, 300))
    t["summary"] = t["summary"].map(lambda s: _clean(s, 300))
    t["topics"] = t["headline"].map(lambda s: "|".join(news.classify(s)))
    t = t.drop_duplicates("headline").sort_values("time")
    return t[COLUMNS]


# ---------------------------------------------------------------------------
# The archive: one CSV per month
# ---------------------------------------------------------------------------
def _month_file(month: pd.Period) -> Path:
    return ARCHIVE_DIR / f"{month}.csv"


def update() -> None:
    """Download any missing months, and refresh the current month (plus the
    previous month during the first days of a new month)."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.now(tz="UTC")
    this_month = now.tz_localize(None).to_period("M")
    refresh = {this_month} | ({this_month - 1} if now.day <= 3 else set())
    for month in pd.period_range(ARCHIVE_START, this_month, freq="M"):
        path = _month_file(month)
        if path.exists() and month not in refresh:
            continue
        start = month.start_time.tz_localize("UTC")
        end = min(month.end_time.tz_localize("UTC"), now)
        table = fetch(start, end)
        if path.exists():
            saved = len(pd.read_csv(path, usecols=["headline"]))
            if len(table) < 0.8 * saved:      # a glitch, not news disappearing
                print(f"{month}: got {len(table):,} articles but {saved:,} are saved; "
                      "keeping the saved copy")
                continue
        table.to_csv(path, index=False)
        print(f"{month}: {len(table):,} articles")


def load_archive() -> pd.DataFrame:
    files = sorted(ARCHIVE_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame(columns=COLUMNS).assign(time=pd.Series(dtype="datetime64[ns, UTC]"))
    t = pd.concat([pd.read_csv(f, keep_default_na=False) for f in files], ignore_index=True)
    t["time"] = pd.to_datetime(t["time"], utc=True, format="ISO8601")
    for column in ("headline", "summary"):   # (older files: broken apostrophes)
        t[column] = t[column].str.replace("\ufffd", "'", regex=False)
    t["day"] = t["time"].dt.tz_convert(MARKET_TZ).dt.tz_localize(None).dt.normalize()
    t["topics"] = t["topics"].map(lambda s: [k for k in s.split("|") if k in news.TOPICS])
    t["text"] = (t["headline"] + " " + t["summary"]).str.lower()   # for searching
    return t.sort_values("time").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Daily counts (same shape as GDELT's timelines, so news.find_spikes works)
# ---------------------------------------------------------------------------
def counts(archive: pd.DataFrame, match: pd.Series, name: str) -> pd.DataFrame:
    """Daily number of matching articles and of all articles in the archive."""
    days = pd.date_range(archive["day"].min(), archive["day"].max(), freq="D")
    total = archive.groupby("day").size().reindex(days, fill_value=0)
    hits = archive[match].groupby("day").size().reindex(days, fill_value=0)
    return pd.DataFrame({"topic": name, "date": days, "articles": hits.values,
                         "all_articles": total.values})


def topic_timelines(archive: pd.DataFrame) -> pd.DataFrame:
    if archive.empty:
        return news.load_timelines().iloc[0:0]
    parts = [counts(archive, archive["topics"].map(lambda ts, k=key: k in ts), key)
             for key in news.TOPICS]
    return pd.concat(parts, ignore_index=True)


def search_mask(archive: pd.DataFrame, query: str) -> pd.Series:
    """Articles matching a search. Words must all appear; "exact phrases" in
    quotes; OR between alternatives, e.g.  Libya OR "Strait of Hormuz"."""
    match = pd.Series(False, index=archive.index)
    for option in re.split(r"\s+OR\s+", query.strip()):
        terms = re.findall(r'"([^"]+)"|(\S+)', option)
        terms = [(phrase or word).lower() for phrase, word in terms]
        terms = [t for t in terms if t not in ("and", "+")]
        if not terms:
            continue
        hit = pd.Series(True, index=archive.index)
        for term in terms:
            hit &= archive["text"].str.contains(r"\b" + re.escape(term), regex=True)
        match |= hit
    return match


def add_headlines(spikes: pd.DataFrame, archive: pd.DataFrame,
                  match_for: callable) -> pd.DataFrame:
    """Attach a headline from around each spike, so every past spike shows
    what the news actually said. Looks on the spike day first, then the day
    before, the day after and two days before (the archive holds only ~10
    oil-market stories a day, so the spike day alone often has none)."""
    if spikes.empty or archive.empty:
        return spikes.assign(headline="")
    by_day = {day: rows for day, rows in archive.groupby("day")}
    found = []
    for _, spike in spikes.iterrows():
        headline = ""
        for offset in (0, -1, 1, -2):
            window = by_day.get(spike["spike_day"] + pd.Timedelta(days=offset))
            if window is None:
                continue
            hits = window[match_for(window, spike)]
            if len(hits):
                headline = hits["headline"].iloc[-1]
                break
        found.append(headline)
    spikes = spikes.assign(headline=found)
    spikes["description"] = [f"{h}<br>{d}" if h else d
                             for h, d in zip(spikes["headline"], spikes["description"])]
    return spikes


def topic_match(window: pd.DataFrame, spike) -> pd.Series:
    """Stories tagged with the spike's topic, or whose summary mentions it."""
    tagged = window["topics"].map(lambda ts: spike["topic"] in ts)
    return tagged | window["text"].str.contains(news.TOPICS[spike["topic"]]["keywords"],
                                                regex=True)


# ---------------------------------------------------------------------------
# "Like this before": past headlines most similar to a given headline
# ---------------------------------------------------------------------------
def build_matcher(archive: pd.DataFrame):
    """Turn every oil-related story into a word-weight vector (TF-IDF): words
    that are rare across the archive (e.g. "Abqaiq") count for more than
    common ones (e.g. "oil"). The headline counts double vs the summary."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    pool = oil_related(archive)
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2,
                                 max_df=0.3, sublinear_tf=True)
    matrix = vectorizer.fit_transform(pool["headline"] + " " + pool["headline"] + " "
                                      + pool["summary"])
    return pool, vectorizer, matrix


def similar(matcher, text: str, before: pd.Timestamp, n: int = 10,
            min_score: float = 0.15, gap_days: int = 7) -> pd.DataFrame:
    """The n past stories most similar to `text`, published before `before`,
    at least gap_days apart (so one story can't fill the list)."""
    pool, vectorizer, matrix = matcher
    scores = (matrix @ vectorizer.transform([text + " " + text]).T).toarray().ravel()
    found = pool.assign(score=scores)
    found = found[(found["score"] >= min_score) & (found["time"] < before)]
    picked = []
    for _, row in found.sort_values("score", ascending=False).iterrows():
        if all(abs((row["day"] - p["day"]).days) >= gap_days for p in picked):
            picked.append(row)
        if len(picked) == n:
            break
    columns = ["time", "day", "headline", "source", "url", "topics", "score"]
    return pd.DataFrame(picked)[columns] if picked else pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# Latest headlines
# ---------------------------------------------------------------------------
def oil_related(t: pd.DataFrame) -> pd.DataFrame:
    tagged = t["topics"].str.len() > 0
    oily = t["headline"].str.lower().str.contains(OIL_WORDS, regex=True)
    return t[tagged | oily]


def latest(hours: int = 48) -> pd.DataFrame:
    """Live: the newest oil headlines (one quick request)."""
    now = pd.Timestamp.now(tz="UTC")
    t = fetch(now - pd.Timedelta(hours=hours), now, timeout=10, max_pages=4, waits=0)
    t["topics"] = t["topics"].map(lambda s: [k for k in s.split("|") if k])
    return oil_related(t).sort_values("time", ascending=False)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "update"
    if command == "update":
        update()
    elif command == "latest":
        for _, h in latest().head(30).iterrows():
            print(f"{h['time']:%m-%d %H:%M} {', '.join(h['topics']) or '-':20} {h['headline'][:90]}")


if __name__ == "__main__":
    main()
