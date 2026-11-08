"""
The "Paper trading bots" tab of the website. Reads the bots' fake-money
account from Alpaca (read-only here - all trading happens in bot.py).
"""

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import bot
import ui

BOT_COLORS = {"weak_dollar": "#2a78d6", "trend_200d": "#eb6834"}


def _load_keys_into_env() -> bool:
    """Use Streamlit Cloud's secrets if present (locally, bot.keys() reads .env)."""
    try:
        for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            os.environ.setdefault(name, st.secrets[name])
    except Exception:
        pass
    try:
        bot.keys()
        return True
    except KeyError:
        return False


@st.cache_data(ttl=5 * 60, show_spinner="Checking the bots' account...")
def load_bot_data():
    if not _load_keys_into_env():
        return None
    trading, data = bot.trading_client(), bot.data_client()
    account = trading.get_account()
    started = pd.Timestamp(account.created_at).tz_convert("America/New_York")

    all_fills = bot.fills(trading)
    books = bot.ledger(all_fills)
    price_now = bot.latest_price(data)
    closes = bot.daily_closes(data, started.tz_convert("UTC").normalize().to_pydatetime())

    # Rebuild each bot's value at every daily close since the start
    fill_day = pd.to_datetime(all_fills["time"], utc=True).dt.tz_convert(
        "America/New_York").dt.tz_localize(None).dt.normalize()
    history = {}
    for name, info in bot.BOTS.items():
        mine = all_fills[all_fills["bot"] == name]
        values = []
        for day, close in closes.items():
            b = bot.book(mine[fill_day[mine.index] <= day], info["budget"])
            values.append(b["cash"] + b["shares"] * close)
        history[name] = pd.Series(values, index=closes.index, dtype=float)

    return {
        "account_equity": float(account.equity), "started": started,
        "books": books, "fills": all_fills, "price_now": price_now,
        "closes": closes, "history": history, "signals": bot.signals(download=False),
    }


def render() -> None:
    ui.eyebrow("Paper trading bots")
    st.subheader("Two bots trading fake money at real prices")
    st.markdown(f"""
Two automated bots trade **fake money** in a paper account at **real market
prices** (via Alpaca). Each starts with **$50,000** and trades **{bot.SYMBOL}**,
a fund that tracks Brent crude futures. They check every weekday shortly
before the 4pm ET close and only trade when their decision changes.

- **Weak dollar bot:** owns {bot.SYMBOL} while the U.S. dollar is below its 50-day average.
- **Trend bot:** owns {bot.SYMBOL} while its price is above its 200-day average.
""")
    try:
        data = load_bot_data()
    except Exception as error:
        st.warning(f"Couldn't reach the bots' account right now ({error}). Try again later.")
        return
    if data is None:
        st.info("The bots' account isn't connected on this copy of the site yet.")
        return

    price = data["price_now"]
    closes = data["closes"]
    first_price = closes.iloc[0] if len(closes) else price
    hold_return = (price / first_price - 1) * 100

    cols = st.columns(len(bot.BOTS) + 1)
    for col, (name, info) in zip(cols, bot.BOTS.items()):
        b = data["books"][name]
        value = b["cash"] + b["shares"] * price
        own, reason = data["signals"][name]
        col.metric(info["label"], f"${value:,.2f}",
                   f"{(value / info['budget'] - 1) * 100:+.2f}% since start", border=True)
        col.caption(f"**Holding:** {f'{b['shares']:,.2f} {bot.SYMBOL}' if b['shares'] > 0 else 'cash'}  \n"
                    f"**Today's signal:** {'own ' + bot.SYMBOL if own else 'cash'}  \n{reason}")
    cols[-1].metric(f"Just holding {bot.SYMBOL}", f"{hold_return:+.2f}%",
                    f"since {data['started']:%b %d, %Y}", delta_color="off", border=True)

    if len(closes) > 1:
        fig = go.Figure()
        for name, values in data["history"].items():
            fig.add_trace(go.Scatter(x=values.index, y=values.values, mode="lines",
                                     name=bot.BOTS[name]["label"],
                                     line=dict(color=BOT_COLORS[name], width=2.5),
                                     hovertemplate="$%{y:,.2f}"))
        hold = 50_000 * closes / closes.iloc[0]
        fig.add_trace(go.Scatter(x=hold.index, y=hold.values, mode="lines",
                                 name=f"Holding {bot.SYMBOL}",
                                 line=dict(color="#898781", width=1.5, dash="dot"),
                                 hovertemplate="$%{y:,.2f}"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                          hovermode="x unified", yaxis_tickprefix="$",
                          yaxis_title="Value of $50,000",
                          legend=dict(orientation="h", yanchor="top", y=-0.12, x=0))
        st.plotly_chart(fig, width="stretch", key="bot_equity")
    else:
        st.caption(f"The bots started on {data['started']:%b %d, %Y}. "
                   "The performance chart appears after a couple of trading days.")

    st.markdown("**Trades**")
    trades = data["fills"]
    if trades.empty:
        st.caption("No trades yet. Each bot trades at its first check before the "
                   "close after its signal says to own oil.")
    else:
        trades = trades.assign(
            bot=trades["bot"].map(lambda b: bot.BOTS[b]["label"]),
            side=trades["side"].str.upper(),
            value=trades["shares"] * trades["price"],
            time=trades["time"].dt.tz_convert("America/New_York"),
        ).sort_values("time", ascending=False)
        st.dataframe(trades, width="stretch", hide_index=True, column_config={
            "time": st.column_config.DatetimeColumn("Time (ET)", format="YYYY-MM-DD HH:mm"),
            "bot": st.column_config.TextColumn("Bot"),
            "side": st.column_config.TextColumn("Side"),
            "shares": st.column_config.NumberColumn("Shares", format="%.3f"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "value": st.column_config.NumberColumn("Value", format="$%,.2f"),
        })
    st.caption(f"Whole paper account: ${data['account_equity']:,.2f}. A research "
               "experiment with fake money, not investment advice. Paper trading "
               "ignores some real-world costs, and a rule that worked in the past "
               "can stop working.")
