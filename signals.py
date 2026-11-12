"""
Market signals: three prices that say something about the oil market beyond
"up or down today".

  1. The futures curve - what oil costs for delivery now vs in a year.
     Near months dearer than later ones ("backwardation") = supplies are
     tight right now; the opposite ("contango") = plenty of oil around.
  2. Brent minus WTI - world oil vs U.S. oil.
  3. The refining margin ("3-2-1 crack spread") - what refiners earn
     turning a barrel of crude into gasoline and diesel.

Pure calculations (no Streamlit); the Market signals tab draws them
(signals_page.py).

    python signals.py snapshot    # save today's curve (run by news.yml)
"""

import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

import live_prices

CURVE_PATH = Path(__file__).parent / "news_data" / "curve.csv"
MONTH_CODES = "FGHJKMNQUVXZ"          # futures month letters, January to December
CURVE_MONTHS = 18                     # how far along the curve we look
ROOTS = {"BRENT": "BZ", "WTI": "CL"}  # Yahoo's futures roots (NYMEX listings)
SINCE = "2015-01-01"                  # "normal" ranges are measured from here
FLAT = 1.0                            # a curve within +-1% is called flat


# ---------------------------------------------------------------------------
# The futures curve
# ---------------------------------------------------------------------------
def _contract(root: str, month: pd.Timestamp) -> str:
    return f"{root}{MONTH_CODES[month.month - 1]}{month.year % 100:02d}.NYM"


def _history(symbol: str, timeout: float = 8) -> pd.Series | None:
    """One contract's daily closes for the past 3 months (None if Yahoo has
    nothing)."""
    try:
        response = requests.get(live_prices.QUOTE_URL.format(symbol=symbol),
                                params={"range": "3mo", "interval": "1d"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        days = (pd.to_datetime(result["timestamp"], unit="s", utc=True)
                .tz_convert(live_prices.MARKET_TZ).tz_localize(None).normalize())
        closes = pd.Series(result["indicators"]["quote"][0]["close"], index=days, dtype=float)
        closes = closes.dropna()
        closes = closes[~closes.index.duplicated(keep="last")]
        last = float(result["meta"]["regularMarketPrice"])
        last_day = (pd.Timestamp(result["meta"]["regularMarketTime"], unit="s", tz="UTC")
                    .tz_convert(live_prices.MARKET_TZ).tz_localize(None).normalize())
        closes.loc[last_day] = last
        return closes.sort_index() if len(closes) else None
    except Exception:
        return None


def curve(market: str = "BRENT", months: int = CURVE_MONTHS) -> pd.DataFrame:
    """Prices for each delivery month, with columns: month (first day of the
    delivery month), contract, and one column per date (today, ~1 month ago,
    ~3 months ago). Empty if Yahoo doesn't answer."""
    root = ROOTS[market]
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    first = today.replace(day=1)
    # A few extra months, because the nearest ones may have stopped trading
    candidates = [first + pd.DateOffset(months=i) for i in range(months + 3)]
    symbols = [_contract(root, m) for m in candidates]
    with ThreadPoolExecutor(max_workers=8) as pool:
        histories = list(pool.map(_history, symbols))
    found = [(m, s, h) for m, s, h in zip(candidates, symbols, histories) if h is not None]
    if not found:
        return pd.DataFrame()
    newest = max(h.index[-1] for _, _, h in found)
    # Contracts that stopped trading (expired) are dropped
    live = [(m, s, h) for m, s, h in found if (newest - h.index[-1]).days <= 4][:months]
    if len(live) < 6:
        return pd.DataFrame()

    def on(h: pd.Series, day: pd.Timestamp) -> float:
        before = h[h.index <= day]
        return float(before.iloc[-1]) if len(before) and (day - before.index[-1]).days <= 5 \
            else float("nan")

    dates = {"now": newest, "1 month ago": newest - pd.DateOffset(months=1),
             "3 months ago": newest - pd.DateOffset(months=3) + pd.Timedelta(days=3)}
    rows = [{"month": m, "contract": s.split(".")[0],
             **{name: on(h, day) for name, day in dates.items()}} for m, s, h in live]
    out = pd.DataFrame(rows)
    out.attrs["dates"] = dates
    return out


def curve_shape(table: pd.DataFrame, column: str = "now", ahead: int = 12) -> dict | None:
    """Front month vs the one `ahead` months later: the gap in $ and %,
    and the name of the shape."""
    if table.empty:
        return None
    # The contract nearest to `ahead` months after the front one (far out,
    # only some months are listed)
    target = table["month"].iloc[0] + pd.DateOffset(months=ahead)
    i = int((table["month"] - target).abs().idxmin())
    if abs((table["month"].iloc[i] - target).days) > 45:
        return None
    front, later = table[column].iloc[0], table[column].iloc[i]
    if pd.isna(front) or pd.isna(later):
        return None
    gap_pct = (front / later - 1) * 100
    shape = ("backwardation" if gap_pct > FLAT else "contango" if gap_pct < -FLAT else "flat")
    return {"front": front, "later": later, "gap": front - later, "gap_pct": gap_pct,
            "shape": shape, "front_month": table["month"].iloc[0],
            "later_month": table["month"].iloc[i]}


def snapshot(path: Path = CURVE_PATH) -> bool:
    """Save today's Brent and WTI curve gaps, so a history builds up (free
    sources don't keep one)."""
    rows = []
    for market in ROOTS:
        table = curve(market)
        shape = curve_shape(table)
        if shape is None:
            print(f"{market}: curve unavailable")
            continue
        rows.append({"date": table.attrs["dates"]["now"].strftime("%Y-%m-%d"), "market": market,
                     "front": round(shape["front"], 2), "month_6": round(curve_shape(table, ahead=6)["later"], 2),
                     "month_12": round(shape["later"], 2)})
        print(f"{market}: {shape['shape']} ({shape['gap_pct']:+.1f}% front vs 12 months out)")
    if not rows:
        return False
    fresh = pd.DataFrame(rows)
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=fresh.columns)
    keep = old[~old.set_index(["date", "market"]).index.isin(
        fresh.set_index(["date", "market"]).index)]
    path.parent.mkdir(exist_ok=True)
    pd.concat([keep, fresh]).sort_values(["date", "market"]).to_csv(path, index=False)
    return True


def load_snapshots(path: Path = CURVE_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "market", "front", "month_6", "month_12"])
    return pd.read_csv(path, parse_dates=["date"])


# ---------------------------------------------------------------------------
# Price gaps: Brent - WTI, and the refining margin
# ---------------------------------------------------------------------------
def spreads(brent: pd.Series, wti: pd.Series, gasoline: pd.Series,
            heating_oil: pd.Series) -> pd.DataFrame:
    """Daily Brent - WTI ($/barrel) and the 3-2-1 refining margin.

    The margin: 3 barrels of Brent make about 2 of gasoline and 1 of diesel
    (heating oil). Product prices are $/gallon; a barrel holds 42 gallons."""
    t = pd.concat({"brent": brent, "wti": wti, "gasoline": gasoline,
                   "heating_oil": heating_oil}, axis=1, sort=True).dropna()
    t["brent_wti"] = t["brent"] - t["wti"]
    t["margin"] = (2 * t["gasoline"] + t["heating_oil"]) / 3 * 42 - t["brent"]
    return t


def standing(series: pd.Series, since: str = SINCE) -> dict:
    """Today's value against its history: the typical range (middle 80% of
    days), the median, and the share of days that were lower."""
    history = series[series.index >= since].dropna()
    now = history.iloc[-1]
    return {"now": now, "day": history.index[-1], "median": history.median(),
            "low": history.quantile(0.1), "high": history.quantile(0.9),
            "pct_below": (history < now).mean() * 100,
            "year_ago": _near(history, history.index[-1] - pd.DateOffset(years=1))}


def _near(series: pd.Series, day: pd.Timestamp) -> float:
    before = series[series.index <= day]
    return float(before.iloc[-1]) if len(before) else float("nan")


def level_word(pct_below: float) -> str:
    """'unusually high', 'high', 'normal', 'low', 'unusually low'."""
    if pct_below >= 90:
        return "unusually high"
    if pct_below >= 70:
        return "high"
    if pct_below > 30:
        return "normal"
    if pct_below > 10:
        return "low"
    return "unusually low"


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "snapshot") == "snapshot":
        sys.exit(0 if snapshot() else 1)
