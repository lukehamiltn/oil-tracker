"""
Live oil prices for the top of the site.

The long price history (FRED) is the official daily spot price, but it is
published about a week late, so on its own the site would show last week's
price. For "right now" we read the front-month futures prices that Yahoo
Finance shows on its public quote pages (delayed about 10 minutes).

If that request fails (Yahoo is busy, or blocks the server), the caller falls
back to the latest FRED price and labels it with its date.
"""

import pandas as pd
import requests

QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SYMBOLS = {"BRENT": "BZ=F", "WTI": "CL=F",      # front-month futures
           "GASOLINE": "RB=F", "HEATING_OIL": "HO=F", "NATGAS": "NG=F",
           "XLE": "XLE", "DOLLAR": "DX-Y.NYB"}  # (dollar: the ICE U.S. dollar index)
MARKET_TZ = "America/New_York"


def quote(market: str, timeout: float = 6) -> dict | None:
    """{'price', 'change_pct' (vs previous close), 'time' (New York)} or None."""
    try:
        response = requests.get(QUOTE_URL.format(symbol=SYMBOLS[market]),
                                params={"range": "5d", "interval": "1d"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        meta = result["meta"]
        price = float(meta["regularMarketPrice"])
        # Previous close = the last daily close before today's bar
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        previous = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
        time = pd.Timestamp(meta["regularMarketTime"], unit="s", tz="UTC").tz_convert(MARKET_TZ)
        return {"price": price, "change_pct": (price / previous - 1) * 100 if previous else None,
                "time": time}
    except Exception as error:          # any network / format problem -> fall back
        print(f"Live price unavailable for {market}: {error!r}")
        return None


def daily_closes(market: str, timeout: float = 8, span: str = "3mo") -> pd.Series:
    """Daily closes (front-month futures for the oil markets) for the last
    `span` (e.g. "3mo", "1y"), by New York date. Today's value is the latest
    price so far. Empty if Yahoo doesn't answer."""
    try:
        response = requests.get(QUOTE_URL.format(symbol=SYMBOLS[market]),
                                params={"range": span, "interval": "1d"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        days = (pd.to_datetime(result["timestamp"], unit="s", utc=True)
                .tz_convert(MARKET_TZ).tz_localize(None).normalize())
        closes = pd.Series(result["indicators"]["quote"][0]["close"], index=days, dtype=float)
        closes = closes.dropna()
        return closes[~closes.index.duplicated(keep="last")]
    except Exception as error:
        print(f"Daily futures closes unavailable for {market}: {error!r}")
        return pd.Series(dtype=float)


def extend(prices: pd.Series, market: str = "BRENT") -> tuple[pd.Series, int]:
    """The official daily spot prices, continued past their last published day
    with futures closes (official prices arrive about a week late).

    Futures and spot prices differ a little, so the futures are scaled to meet
    the spot price on the last official day: the series carries on smoothly
    instead of jumping. Returns (prices, how many days were added)."""
    futures = daily_closes(market)
    last_day = prices.index[-1]
    if futures.empty or futures.index[-1] <= last_day:
        return prices, 0
    on_last_day = futures[futures.index <= last_day]
    if on_last_day.empty:
        return prices, 0
    ratio = prices.iloc[-1] / on_last_day.iloc[-1]
    added = futures[futures.index > last_day] * ratio
    return pd.concat([prices, added.round(2)]), len(added)


if __name__ == "__main__":
    for key in ("BRENT", "WTI"):
        print(key, quote(key))
