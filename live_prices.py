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
SYMBOLS = {"BRENT": "BZ=F", "WTI": "CL=F"}      # front-month futures
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


if __name__ == "__main__":
    for key in SYMBOLS:
        print(key, quote(key))
