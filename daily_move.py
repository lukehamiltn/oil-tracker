"""
"Why oil moved today": today's Brent move, how unusual it is, the headlines
most likely behind it, and what Brent did after past days with a similar move.

Pure calculations (no Streamlit), so they can be tested on their own; the
News tab draws the result (news_page.why_today).
"""

import re

import pandas as pd

# Headlines that report the day's price move ("Oil prices fall as...",
# "Brent hits $94 after..."). These usually say why, in the headline itself.
_SUBJECT = r"\b(oil|crude|brent|wti)\b"
_MOVE_DOWN = r"\b(falls?|fell|drops?|dropped|slips?|slides?|declines?|tumbles?|sinks?|eases?|" \
             r"plunges?|retreats?|dips?|lower|losses|slumps?|weakens?)\b"
_MOVE_UP = r"\b(rises?|rose|gains?|jumps?|climbs?|rall(y|ies)|surges?|rebounds?|higher|" \
           r"advances?|spikes?|soars?|firms?|hits? \$\d+|tops? \$\d+)\b"
_NOT_PRICE = r"\b(production|output|exports?|imports?|stocks? of|inventor|refinery runs)\b"

HISTORY_YEARS = 3      # "bigger than X% of days" compares with this many years
NEXT_DAYS = 5          # "a week later" = 5 trading days


def direction(headline: str) -> int:
    """+1 if the headline reports oil rising, -1 falling, 0 if it isn't a
    price-move headline."""
    text = str(headline).lower()
    if not re.search(_SUBJECT, text) or re.search(_NOT_PRICE, text):
        return 0
    down, up = re.search(_MOVE_DOWN, text), re.search(_MOVE_UP, text)
    if down and not up:
        return -1
    if up and not down:
        return 1
    if up and down:          # "oil rises after falling..." - the first verb wins
        return 1 if up.start() < down.start() else -1
    return 0


def move_stats(brent: pd.Series, change_pct: float) -> dict:
    """How unusual today's move is, and what Brent did over the next week
    after past days that moved by a similar amount in the same direction.

    Similar = same direction, and within the same size band:
    under 1%, 1-2%, 2-4%, or 4%+."""
    brent = brent.dropna()
    daily = brent.pct_change() * 100
    ahead = (brent.shift(-NEXT_DAYS) / brent - 1) * 100
    table = pd.DataFrame({"move": daily, "ahead": ahead}).dropna()

    recent = daily[daily.index >= daily.index[-1] - pd.DateOffset(years=HISTORY_YEARS)].dropna()
    bigger_than = (recent.abs() < abs(change_pct)).mean() * 100

    size = abs(change_pct)
    low, high = next((lo, hi) for lo, hi in [(0, 1), (1, 2), (2, 4), (4, 1e9)] if lo <= size < hi)
    same_way = table["move"] > 0 if change_pct >= 0 else table["move"] < 0
    alike = table[same_way & table["move"].abs().between(low, high, inclusive="left")]
    return {
        "bigger_than": bigger_than,
        "band": (low, high),
        "n": len(alike),
        "avg_ahead": alike["ahead"].mean(),
        "pct_up": (alike["ahead"] > 0).mean() * 100,
        "base_avg": table["ahead"].mean(),
        "base_up": (table["ahead"] > 0).mean() * 100,
        "since": table.index[0],
    }


def band_text(change_pct: float, band: tuple) -> str:
    """'fell 1-2%', 'rose less than 1%', 'fell 4% or more'."""
    verb = "rose" if change_pct >= 0 else "fell"
    low, high = band
    if low == 0:
        return f"{verb} less than 1%"
    if high > 100:
        return f"{verb} {low:.0f}% or more"
    return f"{verb} {low:.0f}–{high:.0f}%"


def likely_reasons(heads: pd.DataFrame, change_pct: float, hot_topics: list[str],
                   n: int = 4) -> pd.DataFrame:
    """The headlines most likely to explain today's move: price-move headlines
    from the last day going the same way as the market first, then the
    newest stories from the topics getting the most extra coverage."""
    if heads.empty:
        return heads
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=30)
    recent = heads[heads["time"] >= since].copy()
    if recent.empty:
        return recent
    recent["direction"] = recent["headline"].map(direction)
    sign = 1 if change_pct >= 0 else -1
    # Headlines that lead with oil ("Brent hits...", "Oil prices fall as...")
    # are about the move; ones that mention it in passing ("Yields jump as oil
    # gains") come after them
    recent["leads"] = recent["headline"].map(
        lambda h: bool(re.search(_SUBJECT, " ".join(str(h).lower().split()[:4]))))
    wraps = recent[recent["direction"] == sign].sort_values(["leads", "time"],
                                                            ascending=[False, False])
    picked = wraps.drop_duplicates("headline").head(n)
    if len(picked) < n and hot_topics:
        rest = recent[~recent["headline"].isin(picked["headline"]) & (recent["direction"] != -sign)]
        for topic in hot_topics:
            about = rest[rest["topics"].map(lambda ts: topic in ts)]
            picked = pd.concat([picked, about.sort_values("time", ascending=False).head(1)])
            if len(picked) >= n:
                break
    return picked.head(n)
