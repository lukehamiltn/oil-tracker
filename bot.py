"""
Paper-trading bots: trade fake money in an Alpaca paper account at real prices.

Two bots share one account, each with its own $50,000 "sleeve", both trading
BNO (a fund tracking Brent crude futures):
  - weak_dollar: own BNO while the U.S. dollar is below its 50-day average
  - trend_200d:  own BNO while BNO's price is above its 200-day average

Every order is labelled with its bot's name (Alpaca's client_order_id, e.g.
"trend_200d-20261109194012"), so each bot's shares and cash can be worked out
from its own fills - see ledger(). The rules are the same functions the
backtest uses (strategies.py).

They run automatically on weekdays shortly before the 4pm ET close
(see .github/workflows/bot.yml) and only trade when a decision changes.

Run it yourself with:
    python bot.py --dry-run     show what each bot would do, place no orders
    python bot.py               decide and trade (only near the close)
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest
from dotenv import load_dotenv

import market_data as md
import strategies as strat

SYMBOL = "BNO"
BOTS = {
    "weak_dollar": {"label": "Weak dollar bot", "budget": 50_000},
    "trend_200d": {"label": "Trend bot (200-day)", "budget": 50_000},
}
INVEST_FRACTION = 0.98                 # keep 2% of a bot's cash as a buffer
TRADE_WINDOW = timedelta(minutes=45)   # only trade in the last 45 min before close


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def keys() -> tuple[str, str]:
    load_dotenv()  # reads .env locally; on GitHub the keys come from secrets
    return os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]


def trading_client() -> TradingClient:
    return TradingClient(*keys(), paper=True)


def data_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(*keys())


# ---------------------------------------------------------------------------
# Prices and signals
# ---------------------------------------------------------------------------
def daily_closes(client: StockHistoricalDataClient, start: datetime) -> pd.Series:
    """BNO daily closes (free data can't include the last 15 minutes)."""
    bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOL, timeframe=TimeFrame.Day, start=start,
        end=datetime.now(timezone.utc) - timedelta(minutes=20),
        adjustment=Adjustment.SPLIT, feed=DataFeed.SIP)).df
    if bars.empty:
        return pd.Series(dtype=float)
    closes = bars.reset_index().set_index("timestamp")["close"]
    closes.index = closes.index.tz_convert("America/New_York").tz_localize(None).normalize()
    return closes


def latest_price(client: StockHistoricalDataClient) -> float:
    trade = client.get_stock_latest_trade(
        StockLatestTradeRequest(symbol_or_symbols=SYMBOL, feed=DataFeed.IEX))
    return float(trade[SYMBOL].price)


def today() -> pd.Timestamp:
    return pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()


def dollar_reading() -> float:
    """Dollar % vs its 50-day average, as publicly known today (saved data)."""
    return float(strat.dollar_trend(md.load_dollar(), pd.DatetimeIndex([today()])).iloc[0])


def trend_reading(client: StockHistoricalDataClient | None = None) -> float:
    """BNO's live price % vs its 200-day average (today counts as one day)."""
    client = client or data_client()
    closes = daily_closes(client, datetime.now(timezone.utc) - timedelta(days=400))
    closes = closes[closes.index < today()]          # completed days only
    closes.loc[today()] = latest_price(client)       # plus today's price so far
    return float(strat.trend_gap(closes).iloc[-1])


def signals(download: bool = True) -> dict[str, tuple[bool, str]]:
    """{bot: (own oil?, human-readable reason)} as of right now."""
    if download:
        md.download_dollar()
    dollar = dollar_reading()
    trend = trend_reading()
    return {
        "weak_dollar": (dollar < 0, f"Dollar {dollar:+.2f}% vs its 50-day average"),
        "trend_200d": (trend > 0, f"{SYMBOL} {trend:+.2f}% vs its 200-day average"),
    }


# ---------------------------------------------------------------------------
# Each bot's own books, rebuilt from its labelled orders
# ---------------------------------------------------------------------------
def fills(client: TradingClient) -> pd.DataFrame:
    """All filled (or partly filled) BNO orders, with the bot that placed them."""
    orders = client.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.ALL, symbols=[SYMBOL], limit=500))
    rows = []
    for o in orders:
        bot = (o.client_order_id or "").rsplit("-", 1)[0]
        if bot in BOTS and o.filled_at is not None and float(o.filled_qty or 0) > 0:
            rows.append({"bot": bot, "time": pd.Timestamp(o.filled_at),
                         "side": o.side.value, "shares": float(o.filled_qty),
                         "price": float(o.filled_avg_price)})
    return pd.DataFrame(rows, columns=["bot", "time", "side", "shares", "price"])


def book(bot_fills: pd.DataFrame, budget: float) -> dict:
    """Shares and cash after a set of one bot's fills (works when empty too)."""
    sign = (bot_fills["side"] == "buy").astype(float) * 2 - 1   # buy +1, sell -1
    shares = sign * bot_fills["shares"].astype(float)
    return {"shares": float(shares.sum()),
            "cash": budget - float((shares * bot_fills["price"].astype(float)).sum())}


def ledger(all_fills: pd.DataFrame) -> dict[str, dict]:
    """{bot: {"shares": ..., "cash": ...}} from each bot's own fills."""
    return {name: book(all_fills[all_fills["bot"] == name], info["budget"])
            for name, info in BOTS.items()}


# ---------------------------------------------------------------------------
# Main: decide and trade
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show the decisions but don't place orders")
    args = parser.parse_args()

    client = trading_client()
    clock = client.get_clock()
    books = ledger(fills(client))
    decisions = signals()

    for bot, (own, reason) in decisions.items():
        b = books[bot]
        print(f"{BOTS[bot]['label']}: {reason} -> {'OWN ' + SYMBOL if own else 'CASH'} "
              f"| holds {b['shares']:.4f} shares, ${b['cash']:,.2f} cash")

    if not clock.is_open:
        print("Market is closed - nothing to do.")
        return
    time_left = clock.next_close - clock.timestamp
    if time_left > TRADE_WINDOW and not args.dry_run:
        print(f"Market closes in {time_left} - too early, waiting for the next run.")
        return
    if client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[SYMBOL])):
        print("An order is still being filled - not placing more.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for bot, (own, _) in decisions.items():
        b = books[bot]
        order = None
        if own and b["shares"] <= 0:
            amount = round(b["cash"] * INVEST_FRACTION, 2)
            print(f"{bot}: BUY ${amount:,.2f} of {SYMBOL}")
            order = MarketOrderRequest(symbol=SYMBOL, notional=amount,
                                       side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
                                       client_order_id=f"{bot}-{stamp}")
        elif not own and b["shares"] > 0:
            print(f"{bot}: SELL {b['shares']:.4f} shares of {SYMBOL}")
            order = MarketOrderRequest(symbol=SYMBOL, qty=round(b["shares"], 9),
                                       side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                                       client_order_id=f"{bot}-{stamp}")
        else:
            print(f"{bot}: already in the right position - no trade.")
        if order is not None and not args.dry_run:
            client.submit_order(order)

    if args.dry_run:
        print("(dry run: no orders placed)")


if __name__ == "__main__":
    main()
