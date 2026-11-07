"""
Paper-trading bot: trades fake money in an Alpaca paper account at real prices.

Strategy: "Weak dollar" (see strategies.py), the rule that held up best in
backtests. Own BNO (a fund tracking Brent crude futures) while the U.S.
dollar is below its 50-day average; otherwise hold cash.

It runs automatically on weekdays shortly before the 4pm ET close
(see .github/workflows/bot.yml) and only trades when the decision changes.

Run it yourself with:
    python bot.py --dry-run     show what it would do, place no orders
    python bot.py               decide and trade (only near the close)
"""

import argparse
import os
from datetime import timedelta

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest
from dotenv import load_dotenv

import market_data as md
import strategies as strat

SYMBOL = "BNO"
INVEST_FRACTION = 0.98            # keep 2% cash as a buffer for price moves
TRADE_WINDOW = timedelta(minutes=45)  # only trade in the last 45 min before close


def trading_client() -> TradingClient:
    load_dotenv()  # reads .env locally; on GitHub the keys come from secrets
    return TradingClient(os.environ["ALPACA_API_KEY"],
                         os.environ["ALPACA_SECRET_KEY"], paper=True)


def current_reading() -> float:
    """Dollar % vs its 50-day average, as publicly known today (saved data)."""
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    return float(strat.dollar_trend(md.load_dollar(), pd.DatetimeIndex([today])).iloc[0])


def todays_signal() -> tuple[bool, float]:
    """(should we own oil?, reading) after downloading the latest dollar data."""
    md.download_dollar()
    reading = current_reading()
    return reading < 0, reading


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show the decision but don't place orders")
    args = parser.parse_args()

    client = trading_client()
    clock = client.get_clock()
    account = client.get_account()
    positions = {p.symbol: p for p in client.get_all_positions()}
    holding = positions.get(SYMBOL)

    own_oil, reading = todays_signal()
    print(f"Dollar is {reading:+.2f}% vs its 50-day average -> "
          f"{'OWN ' + SYMBOL if own_oil else 'CASH'}")
    print(f"Account: equity ${float(account.equity):,.2f}, cash ${float(account.cash):,.2f}, "
          f"{SYMBOL} held: {float(holding.qty) if holding else 0:g} shares")

    if not clock.is_open:
        print("Market is closed - nothing to do.")
        return
    time_left = clock.next_close - clock.timestamp
    if time_left > TRADE_WINDOW and not args.dry_run:
        print(f"Market closes in {time_left} - too early, waiting for the next run.")
        return

    open_orders = client.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.OPEN, symbols=[SYMBOL]))
    if open_orders:
        print("An order is still being filled - not placing another.")
        return

    if own_oil and holding is None:
        amount = round(float(account.cash) * INVEST_FRACTION, 2)
        print(f"BUY ${amount:,.2f} of {SYMBOL}")
        if not args.dry_run:
            client.submit_order(MarketOrderRequest(
                symbol=SYMBOL, notional=amount, side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY))
    elif not own_oil and holding is not None:
        print(f"SELL all {SYMBOL} ({float(holding.qty):g} shares)")
        if not args.dry_run:
            client.close_position(SYMBOL)
    else:
        print("Already in the right position - no trade.")

    if args.dry_run:
        print("(dry run: no orders placed)")


if __name__ == "__main__":
    main()
