"""
The "Paper trading bot" tab of the website. Reads the bot's fake-money
account from Alpaca (read-only here - all trading happens in bot.py).
"""

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest
from dotenv import load_dotenv

from bot import SYMBOL

START_CASH = 100_000


def _keys() -> tuple[str | None, str | None]:
    """Keys from Streamlit Cloud's secrets, or the local .env file."""
    try:
        return st.secrets["ALPACA_API_KEY"], st.secrets["ALPACA_SECRET_KEY"]
    except Exception:
        load_dotenv()
        return os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")


@st.cache_data(ttl=5 * 60, show_spinner="Checking the bot's account...")
def load_bot_data():
    key, secret = _keys()
    if not key or not secret:
        return None
    client = TradingClient(key, secret, paper=True)
    account = client.get_account()

    history = client.get_portfolio_history(
        GetPortfolioHistoryRequest(period="all", timeframe="1D"))
    equity = pd.Series(history.equity or [], index=pd.to_datetime(
        history.timestamp or [], unit="s")).astype(float)
    equity = equity[equity > 0]  # days before the account existed show $0

    orders = client.get_orders(GetOrdersRequest(
        status=QueryOrderStatus.CLOSED, limit=500, symbols=[SYMBOL]))
    trades = pd.DataFrame([{
        "time": o.filled_at, "side": o.side.value.upper(),
        "shares": float(o.filled_qty), "price": float(o.filled_avg_price),
    } for o in orders if o.filled_at is not None])
    if not trades.empty:
        trades["value"] = trades["shares"] * trades["price"]
        trades["time"] = pd.to_datetime(trades["time"]).dt.tz_convert("America/New_York")

    position = next((p for p in client.get_all_positions() if p.symbol == SYMBOL), None)

    # BNO price since the bot started, for the "just hold oil" comparison.
    # (Free data plans can't query the last 15 minutes, hence the end time.)
    start = pd.Timestamp(account.created_at).tz_convert("UTC").normalize()
    bars = StockHistoricalDataClient(key, secret).get_stock_bars(StockBarsRequest(
        symbol_or_symbols=SYMBOL, timeframe=TimeFrame.Day, start=start,
        end=datetime.now(timezone.utc) - timedelta(minutes=20),
        adjustment=Adjustment.ALL, feed=DataFeed.SIP)).df
    bno = pd.Series(dtype=float)
    if not bars.empty:
        bno = bars.reset_index().set_index("timestamp")["close"]
        bno.index = bno.index.tz_convert("America/New_York").tz_localize(None).normalize()

    return {
        "equity_now": float(account.equity), "cash": float(account.cash),
        "started": pd.Timestamp(account.created_at).tz_convert("America/New_York"),
        "equity": equity, "trades": trades, "bno": bno,
        "position": None if position is None else {
            "shares": float(position.qty), "value": float(position.market_value),
            "pnl": float(position.unrealized_pl), "avg_price": float(position.avg_entry_price)},
    }


def render(today_reading: float) -> None:
    st.markdown(f"""
An automated bot trading **${START_CASH:,} of fake money** in a paper account
at **real market prices** (via Alpaca). It follows the *Weak dollar* rule,
which did best in the Strategy lab: **own {SYMBOL}** (a fund that tracks
Brent crude futures) while the U.S. dollar is below its 50-day average,
otherwise hold cash. It checks every weekday shortly before the 4pm ET close
and only trades when the decision changes.
""")
    try:
        data = load_bot_data()
    except Exception as error:
        st.warning(f"Couldn't reach the bot's account right now ({error}). Try again later.")
        return
    if data is None:
        st.info("The bot's account isn't connected on this copy of the site yet.")
        return

    total_return = (data["equity_now"] / START_CASH - 1) * 100
    bno = data["bno"]
    hold_return = (bno.iloc[-1] / bno.iloc[0] - 1) * 100 if len(bno) > 1 else 0.0
    pos = data["position"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bot account value", f"${data['equity_now']:,.2f}", f"{total_return:+.2f}% since start")
    c2.metric(f"Just holding {SYMBOL} instead", f"{hold_return:+.2f}%",
              f"since {data['started']:%b %d, %Y}", delta_color="off")
    c3.metric("Current position", f"{pos['shares']:,.2f} {SYMBOL}" if pos else "Cash",
              f"{pos['pnl']:+,.2f} open P/L" if pos else None)
    c4.metric("Today's signal", f"Own {SYMBOL}" if today_reading < 0 else "Cash",
              f"Dollar {today_reading:+.2f}% vs 50-day avg", delta_color="off")

    equity = data["equity"]
    if len(equity) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity.index, y=equity.values, mode="lines",
                                 name="Bot", line=dict(color="#2a78d6", width=2.5),
                                 hovertemplate="$%{y:,.2f}"))
        if len(bno) > 1:
            hold = START_CASH * bno / bno.iloc[0]
            fig.add_trace(go.Scatter(x=hold.index, y=hold.values, mode="lines",
                                     name=f"Holding {SYMBOL}",
                                     line=dict(color="#898781", width=1.5, dash="dot"),
                                     hovertemplate="$%{y:,.2f}"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                          hovermode="x unified", yaxis_tickprefix="$",
                          legend=dict(orientation="h", yanchor="top", y=-0.12, x=0))
        st.plotly_chart(fig, width="stretch", key="bot_equity")
    else:
        st.caption(f"The bot started on {data['started']:%b %d, %Y}. "
                   "Its performance chart will appear after its first full trading days.")

    st.subheader("Trades")
    if data["trades"].empty:
        st.caption("No trades yet. The bot is waiting for the dollar to drop below "
                   "its 50-day average." if today_reading >= 0 else
                   "No trades yet. It will buy at the next check before the close.")
    else:
        st.dataframe(data["trades"].sort_values("time", ascending=False),
                     width="stretch", hide_index=True, column_config={
            "time": st.column_config.DatetimeColumn("Time (ET)", format="YYYY-MM-DD HH:mm"),
            "side": st.column_config.TextColumn("Side"),
            "shares": st.column_config.NumberColumn("Shares", format="%.3f"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "value": st.column_config.NumberColumn("Value", format="$%,.2f"),
        })
    st.caption("A research experiment with fake money, not investment advice. "
               "Paper trading ignores some real-world costs, and a rule that worked "
               "in the past can stop working.")
