"""
Storylines: big news stories that run for months and come back in waves
(Iran and the Strait of Hormuz, Russia sanctions, Venezuela, trade wars).

For each storyline we keep its daily share of worldwide news since 2015
(Media Cloud), find its waves - stretches when coverage ran far above its
normal - and compare what Brent did during the latest wave with past ones.

    python storylines.py update     # refresh the coverage (run by news.yml)
"""

import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd

import mediacloud_news as mcn

PATH = Path(__file__).parent / "news_data" / "mc_storylines.csv"

STORYLINES = {
    "iran": {
        "label": "Iran and the Strait of Hormuz",
        "summary": "Conflict involving Iran, and threats to shipping through the Strait of "
                   "Hormuz, the route for about a fifth of the world's oil.",
        "query": "Iran AND oil AND (war OR strike OR strikes OR attack OR attacks OR Hormuz "
                 "OR missile OR missiles)",
        "keywords": r"\biran|hormuz|tehran",
        "color": "#e87ba4",
    },
    "russia": {
        "label": "Sanctions on Russian oil",
        "summary": "Sanctions, price caps and embargoes on Russia, one of the world's largest "
                   "oil exporters.",
        "query": 'Russia AND oil AND (sanctions OR "price cap" OR embargo)',
        "keywords": r"russia|moscow|kremlin|urals|rosneft|lukoil",
        "color": "#6250d6",
    },
    "venezuela": {
        "label": "Venezuela",
        "summary": "Venezuela's oil industry, U.S. sanctions and politics. The country holds "
                   "the world's largest proven oil reserves.",
        "query": "Venezuela AND oil",
        "keywords": r"venezuela|caracas|pdvsa|maduro",
        "color": "#eda100",
    },
    "tariffs": {
        "label": "Tariffs and trade wars",
        "summary": "Trade disputes, which can slow economic growth and with it oil demand.",
        "query": '(tariff OR tariffs OR "trade war") AND oil',
        "keywords": r"tariff|trade war|trade deal|trade talks",
        "color": "#2a78d6",
    },
}

WAVE_RATIO = 2.5     # a wave: 7-day coverage at least 2.5x its normal (past year's median)...
WAVE_MIN_DAYS = 5    # ...for at least 5 days,
WAVE_GAP = 21        # with quieter spells shorter than 3 weeks counted as the same wave
PATH_DAYS = 120      # Brent is followed for about 6 months (trading days) from a wave's start


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load(path: Path = PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["storyline", "date", "articles", "all_articles"])
    return pd.read_csv(path, parse_dates=["date"])


def update(path: Path = PATH) -> bool:
    """Full history for new storylines; the last few weeks for the others."""
    import mediacloud.api as mc
    key = mcn.api_key()
    if not key:
        print("No MEDIACLOUD_API_KEY set - skipping.")
        return False
    search = mc.SearchApi(key)
    table = load(path)
    today = dt.datetime.now(dt.timezone.utc).date()
    last = table.groupby("storyline")["date"].max()
    all_ok = True
    for i, (key_, story) in enumerate(STORYLINES.items()):
        start = (mcn.HISTORY_START if key_ not in last
                 else last[key_].date() - dt.timedelta(days=mcn.REFETCH_DAYS))
        if i:
            time.sleep(mcn.WAIT_SECONDS)
        rows = None
        for attempt in range(3):          # Media Cloud sometimes drops a long answer
            try:
                rows = search.story_count_over_time(story["query"], start, today,
                                                    collection_ids=mcn.COLLECTIONS)
                break
            except Exception as error:
                print(f"{key_}: attempt {attempt + 1} failed ({error!r})")
                time.sleep(mcn.WAIT_SECONDS)
        if rows is None:
            all_ok = False
            continue
        fresh = pd.DataFrame(rows)
        if fresh.empty:
            continue
        fresh = pd.DataFrame({"storyline": key_, "date": pd.to_datetime(fresh["date"]),
                              "articles": fresh["count"], "all_articles": fresh["total_count"]})
        keep = table[~((table["storyline"] == key_) & (table["date"] >= fresh["date"].min()))]
        table = pd.concat([keep, fresh], ignore_index=True).sort_values(["storyline", "date"])
        path.parent.mkdir(exist_ok=True)
        table.to_csv(path, index=False, date_format="%Y-%m-%d")
        print(f"{story['label']}: {len(fresh):,} days")
    return all_ok


# ---------------------------------------------------------------------------
# Coverage and waves
# ---------------------------------------------------------------------------
def coverage(table: pd.DataFrame, key: str) -> pd.DataFrame:
    """Daily share of all news, its 7-day average, the normal level (median
    of the past year) and the long-run normal (median of all days)."""
    t = table[table["storyline"] == key].set_index("date").sort_index()
    # Skip days when Media Cloud collected unusually few stories overall
    ok = t["all_articles"] > 0.5 * t["all_articles"].rolling(30, min_periods=5).median()
    share = (t["articles"] / t["all_articles"]).where(ok) * 1e6       # per million stories
    out = pd.DataFrame({"articles": t["articles"], "share": share})
    out["smooth"] = share.rolling(7, min_periods=4).mean()
    out["normal"] = share.rolling(365, min_periods=120).median().shift(7).fillna(share.median())
    out["long_run"] = share.median()
    return out


def waves(cov: pd.DataFrame) -> pd.DataFrame:
    """Stretches of unusually heavy coverage, biggest first by stories."""
    hot = cov.index[cov["smooth"] >= WAVE_RATIO * cov["normal"]]
    spans, start, last = [], None, None
    for day in hot:
        if start is not None and (day - last).days > WAVE_GAP:
            spans.append((start, last))
            start = None
        start = day if start is None else start
        last = day
    if start is not None:
        spans.append((start, last))
    rows = []
    for a, b in spans:
        if (b - a).days + 1 < WAVE_MIN_DAYS:
            continue
        seg = cov.loc[a:b]
        peak = seg["share"].idxmax()
        rows.append({"start": a, "end": b, "days": (b - a).days + 1, "peak": peak,
                     "peak_x": seg["smooth"].max() / cov["long_run"].iloc[0],
                     "stories": int(seg["articles"].sum())})
    columns = ["start", "end", "days", "peak", "peak_x", "stories"]
    return pd.DataFrame(rows, columns=columns)


def major(w: pd.DataFrame, most: int = 5, min_peak: float = 4.0) -> pd.DataFrame:
    """The waves worth comparing: the `most` biggest (by stories) of those
    whose coverage reached at least `min_peak` times the long-run normal,
    newest first."""
    if w.empty:
        return w
    big = w[w["peak_x"] >= min_peak]
    if big.empty:
        big = w
    return big.sort_values("stories", ascending=False).head(most).sort_values("start",
                                                                               ascending=False)


def wave_name(wave) -> str:
    return f"{wave['start']:%b} {wave['start'].year} wave"


def turning_points(cov: pd.DataFrame, wave, n: int = 5, apart: int = 10) -> list:
    """The busiest days of a wave, at least `apart` days from each other."""
    seg = cov.loc[wave["start"]:wave["end"], "share"].dropna().sort_values(ascending=False)
    picked = []
    for day in seg.index:
        if all(abs((day - p).days) >= apart for p in picked):
            picked.append(day)
        if len(picked) == n:
            break
    return sorted(picked)


def top_headline(archive: pd.DataFrame, key: str, day: pd.Timestamp) -> pd.Series | None:
    """The saved headline that best stands for a storyline on a day (that
    day or the next, since a story often breaks late)."""
    if archive.empty:
        return None
    window = archive[(archive["day"] >= day) & (archive["day"] <= day + pd.Timedelta(days=1))]
    hits = window[window["headline"].str.contains(STORYLINES[key]["keywords"], case=False,
                                                  regex=True)]
    if hits.empty:
        return None
    # prefer headlines that also mention oil, then real articles over flashes
    oil = hits["headline"].str.contains(r"\b(?:oil|crude|brent|wti|barrel)", case=False, regex=True)
    has_summary = hits["summary"].fillna("").str.len() > 0
    ranked = hits.assign(_oil=oil, _art=has_summary).sort_values(["_oil", "_art", "time"],
                                                                 ascending=[False, False, True])
    return ranked.iloc[0]


# ---------------------------------------------------------------------------
# Brent during each wave
# ---------------------------------------------------------------------------
def brent_path(brent: pd.Series, start: pd.Timestamp, days: int = PATH_DAYS) -> pd.Series:
    """Brent's % change from the last close before `start`, by trading day."""
    before = brent[brent.index < start]
    if before.empty:
        return pd.Series(dtype=float)
    base = before.iloc[-1]
    after = brent[brent.index >= start].iloc[:days]
    path = (after / base - 1) * 100
    return pd.concat([pd.Series([0.0]), pd.Series(path.values)], ignore_index=True)


def wave_moves(brent: pd.Series, wave) -> dict:
    """Brent after 1 week, 1 month and 3 months, and over the whole wave."""
    path = brent_path(brent, wave["start"])
    at = lambda n: path.iloc[n] if len(path) > n else float("nan")
    during = brent[(brent.index >= wave["start"]) & (brent.index <= wave["end"])]
    before = brent[brent.index < wave["start"]]
    whole = ((during.iloc[-1] / before.iloc[-1] - 1) * 100
             if len(during) and len(before) else float("nan"))
    return {"week": at(5), "month": at(21), "quarter": at(63), "whole": whole,
            "low": path.min() if len(path) else float("nan"),
            "high": path.max() if len(path) else float("nan")}


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "update") == "update":
        sys.exit(0 if update() else 1)
