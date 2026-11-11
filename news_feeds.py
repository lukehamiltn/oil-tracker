"""
Real news articles from established publishers, read from their public news
feeds (RSS). These power the "Latest headlines" list, so every story links to
a full article on the publisher's own site.

The site reads the feeds live (refreshed every 15 minutes). The GitHub news
job also saves every oil-related article to news_data/feeds/YYYY-MM.csv, so
there is a growing archive of real articles for the rest of the site.

Run it yourself:
    python news_feeds.py           # show the latest oil-related articles
    python news_feeds.py update    # add new articles to the archive
"""

import html
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

import news

ARCHIVE_DIR = Path(__file__).parent / "news_data" / "feeds"
COLUMNS = ["time", "headline", "summary", "source", "url", "topics"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OilTracker/1.0; news reader)"}

# (publisher, feed address, specialist?)  "Specialist" = an energy or shipping
# publication (kept for reference; every story, from any feed, still has to be
# about oil to be shown).
FEEDS = [
    # Oil & energy
    ("OilPrice.com", "https://oilprice.com/rss/main", True),
    ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx", True),
    ("World Oil", "https://www.worldoil.com/rss?feed=news", True),
    ("CNBC Energy", "https://www.cnbc.com/id/19836768/device/rss/rss.html", True),
    ("U.S. EIA", "https://www.eia.gov/rss/todayinenergy.xml", True),
    ("U.S. EIA", "https://www.eia.gov/rss/press_rss.xml", True),
    ("Offshore Energy", "https://www.offshore-energy.biz/feed/", True),
    ("Kpler", "https://www.kpler.com/blog/rss.xml", True),
    # Shipping
    ("gCaptain", "https://gcaptain.com/feed/", True),
    ("Splash247", "https://splash247.com/feed/", True),
    ("Hellenic Shipping News", "https://www.hellenicshippingnews.com/feed/", True),
    # World & business news
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", False),
    ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", False),
    ("The Guardian", "https://www.theguardian.com/business/rss", False),
    ("The Guardian", "https://www.theguardian.com/world/rss", False),
    ("CNBC", "https://www.cnbc.com/id/100727362/device/rss/rss.html", False),
    ("NPR", "https://feeds.npr.org/1006/rss.xml", False),
    ("NPR", "https://feeds.npr.org/1004/rss.xml", False),
    ("DW", "https://rss.dw.com/rdf/rss-en-all", False),
    ("France 24", "https://www.france24.com/en/rss", False),
    ("Euronews", "https://www.euronews.com/rss", False),
    ("CBS News", "https://www.cbsnews.com/latest/rss/world", False),
    ("ABC News", "https://abcnews.go.com/abcnews/internationalheadlines", False),
    ("Fox Business", "https://moxie.foxbusiness.com/google-publisher/latest.xml", False),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", False),
    ("Axios", "https://api.axios.com/feed/", False),
    ("South China Morning Post", "https://www.scmp.com/rss/91/feed", False),
    ("Japan Times", "https://www.japantimes.co.jp/feed/", False),
    # Middle East
    ("The National", "https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml", False),
    ("Middle East Eye", "https://www.middleeasteye.net/rss", False),
    ("Al-Monitor", "https://www.al-monitor.com/rss", False),
    ("Times of Israel", "https://www.timesofisrael.com/feed/", False),
]

# A story counts if its headline or summary mentions one of these
OIL_TERMS = re.compile(
    r"\boil\b|\bcrude\b|\bopec|\bbrent\b|\bwti\b|barrels?\b|gasoline|\bpetrol\b|diesel|"
    r"refiner|pipeline|tanker|\blng\b|natural gas|fuel prices|hormuz|red sea|houthi|"
    r"bab.el.mandeb|aramco|petroleum|energy prices|oilfield|shale", re.IGNORECASE)

ATOM = "{http://www.w3.org/2005/Atom}"
RSS1 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _text(item, *tags) -> str:
    for tag in tags:
        node = item.find(tag)
        if node is not None:
            if tag.endswith("link") and node.get("href"):
                return node.get("href")
            if node.text:
                return node.text.strip()
    return ""


def _clean(text: str, limit: int = 240) -> str:
    """Plain text from a feed's summary: no HTML, no entities, cut at a word."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"
    return text


def _time(text: str):
    if not text:
        return pd.NaT
    try:
        return pd.Timestamp(parsedate_to_datetime(text)).tz_convert("UTC")
    except (TypeError, ValueError, IndexError):
        try:
            stamp = pd.Timestamp(text)
            return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        except (TypeError, ValueError):
            return pd.NaT


def read_feed(source: str, url: str, timeout: float = 8) -> list[dict]:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry") or root.findall(f".//{RSS1}item")
    rows = []
    for item in items:
        headline = _clean(_text(item, "title", f"{ATOM}title", f"{RSS1}title"), 300)
        link = _text(item, "link", f"{ATOM}link", f"{RSS1}link")
        if not headline or not link.startswith("http"):
            continue
        rows.append({
            "time": _time(_text(item, "pubDate", f"{ATOM}updated", f"{ATOM}published",
                                f"{DC}date")),
            "headline": headline,
            "summary": _clean(_text(item, "description", f"{ATOM}summary", f"{RSS1}description")),
            "source": source,
            "url": link.strip(),
        })
    return rows


def fetch(feeds=FEEDS, timeout: float = 8, oil_only: bool = True) -> pd.DataFrame:
    """The latest articles from every feed (feeds that fail are skipped).
    oil_only: keep just the stories about oil (False = everything, which is
    used to find coverage of newswire flashes about e.g. Iran or the Fed)."""
    def one(feed):
        source, url, specialist = feed
        try:
            rows = read_feed(source, url, timeout)
        except Exception as error:
            print(f"Feed unavailable: {source} ({type(error).__name__})")
            return []
        for row in rows:
            row["specialist"] = specialist
        return rows

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = [row for part in pool.map(one, feeds) for row in part]
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    t = pd.DataFrame(rows).dropna(subset=["time"])
    text = t["headline"] + " " + t["summary"]
    t["topics"] = t["headline"].map(news.classify)
    # Every story must actually be about oil: mention it, or fuel, refineries,
    # tankers, Hormuz... (a topic tag alone isn't enough: "Middle East
    # conflict" would let in every story about the region)
    if oil_only:
        t = t[text.str.contains(OIL_TERMS)]
    t = t.sort_values("time", ascending=False)
    t = t.drop_duplicates("url").drop_duplicates("headline")
    return t[COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------
def _month_file(month: pd.Period) -> Path:
    return ARCHIVE_DIR / f"{month}.csv"


def update() -> None:
    """Add any new articles to this month's (and last month's) archive file."""
    fresh = fetch()
    if fresh.empty:
        print("No articles fetched.")
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    fresh = fresh.assign(topics=fresh["topics"].map("|".join))
    added = 0
    for month, part in fresh.groupby(fresh["time"].dt.tz_localize(None).dt.to_period("M")):
        path = _month_file(month)
        saved = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLUMNS)
        new = part[~part["url"].isin(set(saved["url"]))]
        if new.empty:
            continue
        merged = pd.concat([saved, new.assign(time=new["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"))])
        merged.sort_values("time").to_csv(path, index=False)
        added += len(new)
    print(f"Added {added} new articles to {ARCHIVE_DIR}")


def load_archive() -> pd.DataFrame:
    files = sorted(ARCHIVE_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    t = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    t["time"] = pd.to_datetime(t["time"], utc=True)
    t["summary"] = t["summary"].fillna("")
    t["topics"] = t["topics"].fillna("").map(lambda s: [k for k in s.split("|") if k])
    return t.sort_values("time", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "") == "update":
        update()
    else:
        latest = fetch()
        print(f"{len(latest)} oil-related articles from "
              f"{latest['source'].nunique()} publishers")
        for _, a in latest.head(25).iterrows():
            print(f"{a['time']:%m-%d %H:%M} {a['source'][:16]:16} {a['headline'][:90]}")


# ---------------------------------------------------------------------------
# Coverage for newswire flashes
# ---------------------------------------------------------------------------
def match_coverage(flashes: pd.DataFrame, articles: pd.DataFrame, window_hours: int = 36,
                   min_score: float = 0.2, top: int = 2) -> list[list[dict]]:
    """For each one-line flash, the real articles most like it (same story),
    published within `window_hours` of it: [[{source, headline, url}, ...], ...]."""
    if flashes.empty or articles.empty:
        return [[] for _ in range(len(flashes))]
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = (articles["headline"] + " " + articles["headline"] + " " + articles["summary"]).tolist()
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform(docs + flashes["headline"].tolist())
    art, fl = matrix[:len(docs)], matrix[len(docs):]
    scores = (fl @ art.T).toarray()
    times = pd.to_datetime(articles["time"], utc=True)
    out = []
    for i, (_, flash) in enumerate(flashes.iterrows()):
        gap_hours = (times - pd.Timestamp(flash["time"])).dt.total_seconds().abs() / 3600
        near = (gap_hours <= window_hours).to_numpy()
        order = [j for j in scores[i].argsort()[::-1] if near[j] and scores[i][j] >= min_score]
        picked, seen = [], set()
        for j in order:
            a = articles.iloc[j]
            if a["source"] in seen:
                continue
            seen.add(a["source"])
            picked.append({"source": a["source"], "headline": a["headline"], "url": a["url"],
                           "score": round(float(scores[i][j]), 3)})
            if len(picked) == top:
                break
        out.append(picked)
    return out
