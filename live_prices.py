"""
Live oil prices for the top of the site.

The long price history (FRED) is the official daily spot price, but it is
published about a week late, so on its own the site would show last week's
price. For "right now" we read the front-month futures prices that Yahoo
Finance shows on its public quote pages (delayed about 10 minutes).

If Yahoo stops answering (it's busy, blocks the server, or changes its
format), we estimate instead: start from the last futures closes we saved
(news.yml runs `python live_prices.py save` every 3 hours) and move them by
how much oil funds traded on Alpaca have moved since (BNO follows Brent, USO
follows WTI). If that fails too, the caller falls back to the latest FRED
price and labels it with its date.
"""

import sys
import threading
import time as _time
from pathlib import Path

import pandas as pd
import requests

QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SYMBOLS = {"BRENT": "BZ=F", "WTI": "CL=F",      # front-month futures
           "GASOLINE": "RB=F", "HEATING_OIL": "HO=F", "NATGAS": "NG=F",
           "XLE": "XLE", "DOLLAR": "DX-Y.NYB",  # (dollar: the ICE U.S. dollar index)
           "GOLD": "GC=F"}                         # COMEX gold, $ per ounce
MARKET_TZ = "America/New_York"

SAVED_PATH = Path(__file__).parent / "news_data" / "futures_closes.csv"
# Funds that hold the same futures, for estimates when Yahoo is down
PROXIES = {"BRENT": "BNO", "WTI": "USO", "GASOLINE": "UGA", "NATGAS": "UNG", "GOLD": "GLD"}
ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/{symbol}/{what}"

# Several parts of the page ask for the same prices; keep each answer for a
# few minutes so Yahoo is asked once (faster, and less likely to be blocked)
_MEMO: dict = {}
_MEMO_LOCK = threading.Lock()
MEMO_SECONDS = 10 * 60


def _remember(key, make):
    now = _time.time()
    with _MEMO_LOCK:
        hit = _MEMO.get(key)
    if hit and now - hit[0] < MEMO_SECONDS:
        return hit[1]
    value = make()
    if value is not None and not (isinstance(value, pd.Series) and value.empty):
        with _MEMO_LOCK:
            for old in [k for k, (t, _) in _MEMO.items() if now - t >= MEMO_SECONDS]:
                del _MEMO[old]
            _MEMO[key] = (now, value)
    return value


# Futures roots by market (NYMEX), for finding the actual contract behind the
# "front month" price. Yahoo's front-month series (e.g. NG=F) jumps from one
# contract to the next each month: on Nov 20, 2026 gas "rose 14.7%" only
# because NG=F switched from the December to the January contract. So daily
# changes and recent charts use the one contract it's tracking right now.
CONTRACT_ROOTS = {"BRENT": "BZ", "WTI": "CL", "NATGAS": "NG", "GASOLINE": "RB", "HEATING_OIL": "HO",
                  "GOLD": "GC"}
EXCHANGES = {"GC": "CMX"}           # gold trades on COMEX; the rest on NYMEX
_MONTH_CODES = "FGHJKMNQUVXZ"


def _chart(symbol: str, span: str, timeout: float) -> dict:
    response = requests.get(QUOTE_URL.format(symbol=symbol), params={"range": span, "interval": "1d"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    response.raise_for_status()
    return response.json()["chart"]["result"][0]


def front_contract(market: str, timeout: float = 6) -> str:
    """The Yahoo symbol of the contract the front-month price is tracking right
    now (e.g. "NGF27.NYM"), or the front-month symbol itself if it can't be
    matched. Remembered for 30 minutes."""
    def find() -> str | None:
        root = CONTRACT_ROOTS.get(market)
        if not root:
            return None
        try:
            price = float(_chart(SYMBOLS[market], "5d", timeout)["meta"]["regularMarketPrice"])
            first = pd.Timestamp.now(tz=MARKET_TZ).tz_localize(None).normalize().replace(day=1)
            for i in range(5):
                month = first + pd.DateOffset(months=i)
                symbol = (f"{root}{_MONTH_CODES[month.month - 1]}{month.year % 100:02d}."
                          f"{EXCHANGES.get(root, 'NYM')}")
                try:
                    other = float(_chart(symbol, "5d", timeout)["meta"]["regularMarketPrice"])
                except Exception:
                    continue
                if abs(other / price - 1) < 0.0025:
                    return symbol
        except Exception as error:
            print(f"Couldn't match the front contract for {market}: {error!r}")
        return None
    return _remember(("front", market, int(_time.time() // 1800)), find) or SYMBOLS[market]


def _yahoo_quote(market: str, timeout: float = 6) -> dict | None:
    """{'price', 'change_pct' (vs previous close), 'time' (New York)} or None."""
    try:
        result = _chart(front_contract(market, timeout), "5d", timeout)
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


def _yahoo_closes(market: str, timeout: float = 8, span: str = "3mo") -> pd.Series:
    """Daily closes for the last `span` (e.g. "3mo", "1y"), by New York date,
    of the futures contract the front-month price is tracking now (so the
    monthly switch to the next contract doesn't show up as a fake jump).
    Today's value is the latest price so far. Empty if Yahoo doesn't answer."""
    try:
        result = _chart(front_contract(market, timeout), span, timeout)
        days = (pd.to_datetime(result["timestamp"], unit="s", utc=True)
                .tz_convert(MARKET_TZ).tz_localize(None).normalize())
        closes = pd.Series(result["indicators"]["quote"][0]["close"], index=days, dtype=float)
        closes = closes.dropna()
        return closes[~closes.index.duplicated(keep="last")]
    except Exception as error:
        print(f"Daily futures closes unavailable for {market}: {error!r}")
        return pd.Series(dtype=float)


# ---------------------------------------------------------------------------
# The backup: saved futures closes, moved by oil funds on Alpaca
# ---------------------------------------------------------------------------
def save(path: Path = SAVED_PATH) -> bool:
    """Add the last year of daily futures closes to the saved file."""
    rows = []
    for market in PROXIES:
        closes = _yahoo_closes(market, span="1y")
        # today's bar is still moving; keep finished days only
        closes = closes[closes.index < pd.Timestamp.now(tz=MARKET_TZ).tz_localize(None).normalize()]
        rows.append(pd.DataFrame({"market": market, "date": closes.index, "close": closes.values.round(2)}))
        print(f"{market}: {len(closes)} days")
    fresh = pd.concat(rows)
    if fresh.empty:
        return False
    old = load_saved(path)
    keep = old[~old.set_index(["market", "date"]).index.isin(
        fresh.set_index(["market", "date"]).index)]
    path.parent.mkdir(exist_ok=True)
    (pd.concat([keep, fresh]).sort_values(["market", "date"])
     .to_csv(path, index=False, date_format="%Y-%m-%d"))
    return True


def load_saved(path: Path = SAVED_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["market", "date", "close"])
    return pd.read_csv(path, parse_dates=["date"])


def _alpaca(symbol: str, what: str, params: dict, timeout: float = 8) -> dict:
    import market_news                     # (it knows where the Alpaca keys live)
    response = requests.get(ALPACA_DATA.format(symbol=symbol, what=what),
                            params={"feed": "iex", **params},
                            headers=market_news._headers(), timeout=timeout)
    response.raise_for_status()
    return response.json()


def _fund_closes(symbol: str, days: int = 120) -> pd.Series:
    start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    bars = _alpaca(symbol, "bars", {"timeframe": "1Day", "start": start,
                                    "adjustment": "split", "limit": 1000}).get("bars") or []
    if not bars:
        return pd.Series(dtype=float)
    days_ = (pd.to_datetime([b["t"] for b in bars], utc=True)
             .tz_convert(MARKET_TZ).tz_localize(None).normalize())
    return pd.Series([b["c"] for b in bars], index=days_, dtype=float)


def _anchor(market: str):
    """The last saved futures close, its day, and the fund's daily closes."""
    saved = load_saved()
    saved = saved[saved["market"] == market].set_index("date")["close"].sort_index()
    if saved.empty or market not in PROXIES:
        return None
    fund = _fund_closes(PROXIES[market])
    both = fund.index.intersection(saved.index)
    if not len(both):
        return None
    day = both[-1]
    return saved, day, fund


def backup_closes(market: str) -> pd.Series:
    """Saved futures closes, continued past the last saved day by the fund's
    moves. Empty if there's nothing to go on."""
    try:
        got = _anchor(market)
        if got is None:
            return pd.Series(dtype=float)
        saved, day, fund = got
        later = fund[fund.index > day] / fund[day] * saved[day]
        return pd.concat([saved[saved.index <= day], later.round(2)])
    except Exception as error:
        print(f"Backup closes unavailable for {market}: {error!r}")
        return pd.Series(dtype=float)


def backup_quote(market: str) -> dict | None:
    """An estimated live price: the last saved futures close moved by the
    fund's move since. Marked with 'estimated' and the fund's symbol."""
    try:
        got = _anchor(market)
        if got is None:
            return None
        saved, day, fund = got
        symbol = PROXIES[market]
        trade = _alpaca(symbol, "trades/latest", {})["trade"]
        now_price = float(trade["p"])
        time = pd.Timestamp(trade["t"]).tz_convert(MARKET_TZ)
        price = saved[day] * now_price / fund[day]
        before = fund[fund.index < time.tz_localize(None).normalize()]
        change = (now_price / before.iloc[-1] - 1) * 100 if len(before) else None
        return {"price": price, "change_pct": change, "time": time, "estimated": symbol}
    except Exception as error:
        print(f"Backup price unavailable for {market}: {error!r}")
        return None


# ---------------------------------------------------------------------------
# What the rest of the site calls
# ---------------------------------------------------------------------------
def quote(market: str, timeout: float = 6) -> dict | None:
    """{'price', 'change_pct' (vs previous close), 'time' (New York)}, from
    Yahoo, else estimated from an oil fund (then also 'estimated': the fund),
    else None. Kept for 5 minutes."""
    return _remember(("quote", market, int(_time.time() // 300)),
                     lambda: _yahoo_quote(market, timeout) or backup_quote(market))


def daily_closes(market: str, timeout: float = 8, span: str = "3mo") -> pd.Series:
    """Daily futures closes (see _yahoo_closes); estimated from saved closes
    and an oil fund if Yahoo doesn't answer."""
    def get():
        closes = _yahoo_closes(market, timeout, span)
        return closes if len(closes) else backup_closes(market)
    return _remember(("closes", market, span), get).copy()


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
    if len(sys.argv) > 1 and sys.argv[1] == "save":
        sys.exit(0 if save() else 1)
    for key in ("BRENT", "WTI"):
        print(key, quote(key), backup_quote(key))
