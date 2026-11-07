"""
Oil Tracker website.

Run it with:   streamlit run app.py
Then it opens in your browser at http://localhost:8501
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import backtest as bt
import bot_dashboard
import conditions
import event_study as es
import fed_events as fed
import fetch_prices
import inventory_events as inv
import market_data as md
import strategies as strat

st.set_page_config(page_title="Oil Tracker", page_icon="🛢️", layout="wide")

HORIZON_NAMES = {1: "1 day", 5: "1 week (5 trading days)", 20: "1 month (20 trading days)"}
PCT = "%+.1f%%"


# ---------------------------------------------------------------------------
# Data - cached so the site doesn't redo the work on every click.
# ttl = refresh at most every 6 hours (downloads fresh data each time).
# ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 60 * 60, show_spinner="Loading the latest oil data...")
def get_data():
    # Download fresh data. If a source is temporarily down, carry on with
    # the copy we already have (if any) rather than crashing the site.
    for download in (fetch_prices.main, inv.download_inventories, md.main,
                     fed.download_fed):
        try:
            download()
        except Exception as error:
            print(f"Download failed, using saved data instead: {error}")
    prices = es.load_prices()
    opec = es.compute_results(prices, es.load_events())
    inv_events = inv.build_events(inv.load_inventories())
    inventory = es.compute_results(prices, inv_events)
    fed_results = es.compute_results(prices, fed.build_events(fed.load_fed()))
    features = strat.build_features(prices)
    backtests = bt.run_all(features)
    return prices, opec, inventory, inv_events, fed_results, features, backtests


(prices, (opec_results, opec_paths), (inv_results, inv_paths), inv_events,
 (fed_results, fed_paths), features, (bt_results, bt_metrics)) = get_data()

STRATEGY_COLORS = {"buy_and_hold": "#898781", "trend_200d": "#2a78d6",
                   "big_build_rebound": "#eb6834", "tight_inventories": "#1baf7a",
                   "crowded_short": "#eda100", "weak_dollar": "#e87ba4"}


# ---------------------------------------------------------------------------
# Reusable building blocks (used by both tabs)
# ---------------------------------------------------------------------------
def style_chart(fig: go.Figure, y_title: str, height: int = 430) -> go.Figure:
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    fig.add_vline(x=0, line_color="#898781", line_dash="dot", line_width=1,
                  annotation_text="close before announcement",
                  annotation_font_size=11, annotation_font_color="#898781")
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        xaxis_title="Trading days from the close before the announcement",
        yaxis_title=y_title, yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0),
    )
    return fig


def average_path(paths: dict, dates) -> pd.Series:
    return pd.concat([paths[d] for d in dates], axis=1).mean(axis=1)


def summary_table(results, cat_col, categories, labels, horizon, key):
    col = f"day_{horizon}_pct"
    summary = (results.groupby(cat_col)[col]
               .agg(events="count", average="mean", median="median",
                    pct_up=lambda s: (s > 0).mean() * 100, best="max", worst="min")
               .reindex(categories).dropna(how="all"))
    summary.index = [labels[c] for c in summary.index]
    st.dataframe(summary, width="stretch", key=key, column_config={
        "events": st.column_config.NumberColumn("Events"),
        "average": st.column_config.NumberColumn("Average", format=PCT),
        "median": st.column_config.NumberColumn("Median", format=PCT),
        "pct_up": st.column_config.NumberColumn("Times price rose", format="%.0f%%"),
        "best": st.column_config.NumberColumn("Best", format=PCT),
        "worst": st.column_config.NumberColumn("Worst", format=PCT),
    })
    st.caption(f"For comparison: on any ordinary day, Brent's typical move over "
               f"{HORIZON_NAMES[horizon]} is about ±{es.typical_move(prices, horizon):.1f}%. "
               "Results smaller than that may just be normal noise.")


def comparison_section(results, paths, cat_col, categories, labels, colors, key):
    """Chart of the average path for every category + summary table."""
    fig = go.Figure()
    for cat in categories:
        dates = results.loc[results[cat_col] == cat, "date"]
        if dates.empty:
            continue
        avg = average_path(paths, dates)
        fig.add_trace(go.Scatter(
            x=avg.index, y=avg.values, mode="lines",
            name=f"{labels[cat]} ({len(dates)})",
            line=dict(color=colors[cat], width=2.5), hovertemplate="%{y:+.1f}%"))
    st.plotly_chart(style_chart(fig, "Average % change in Brent"), width="stretch",
                    key=f"{key}_avg_chart")

    horizon = st.radio("Measure the change after:", es.HORIZONS, index=0, horizontal=True,
                       format_func=lambda h: HORIZON_NAMES[h], key=f"{key}_horizon")
    summary_table(results, cat_col, categories, labels, horizon, key=f"{key}_summary")


def drilldown_section(results, paths, cat_col, categories, labels, colors,
                      table_columns, key):
    """Pick one category: see each event (or the spread, if many) + a table."""
    cat = st.selectbox("Category", categories, format_func=lambda c: labels[c],
                       key=f"{key}_select")
    group = results[results[cat_col] == cat].sort_values("date", ascending=False)
    color = colors[cat]
    fig = go.Figure()

    if len(group) <= 60:
        # Few events: draw each one as its own faint line
        for _, event in group.iterrows():
            path = paths[event["date"]]
            fig.add_trace(go.Scatter(
                x=path.index, y=path.values, mode="lines", showlegend=False,
                line=dict(color=color, width=1), opacity=0.3,
                hovertemplate=f"<b>{event['date']:%b %d, %Y}</b><br>"
                              f"{event['description']}<br>%{{y:+.1f}}%<extra></extra>"))
        note = "Thin lines are individual events (hover to see which). Thick line = average."
    else:
        # Many events: show the middle half of outcomes as a shaded band
        all_paths = pd.concat([paths[d] for d in group["date"]], axis=1)
        low, high = all_paths.quantile(0.25, axis=1), all_paths.quantile(0.75, axis=1)
        fig.add_trace(go.Scatter(x=high.index, y=high.values, mode="lines",
                                 line=dict(width=0), showlegend=False,
                                 hovertemplate="75th percentile: %{y:+.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=low.index, y=low.values, mode="lines",
                                 line=dict(width=0), fill="tonexty", fillcolor=color,
                                 opacity=0.2, name="Middle 50% of outcomes",
                                 hovertemplate="25th percentile: %{y:+.1f}%<extra></extra>"))
        note = ("Shaded band = where the middle half of outcomes landed. "
                "Thick line = average. Wide band = the average is not very reliable.")

    avg = average_path(paths, group["date"])
    fig.add_trace(go.Scatter(x=avg.index, y=avg.values, mode="lines", name="Average",
                             line=dict(color=color, width=3.5),
                             hovertemplate="Average: %{y:+.1f}%<extra></extra>"))
    fig = style_chart(fig, "% change in Brent")
    fig.update_layout(hovermode="closest" if len(group) <= 60 else "x unified")
    st.plotly_chart(fig, width="stretch", key=f"{key}_drill_chart")
    st.caption(note)

    st.dataframe(group[list(table_columns)], width="stretch", hide_index=True,
                 key=f"{key}_events", column_config=table_columns)


HORIZON_COLUMNS = {
    "day_1_pct": st.column_config.NumberColumn("1 day", format=PCT),
    "day_5_pct": st.column_config.NumberColumn("1 week", format=PCT),
    "day_20_pct": st.column_config.NumberColumn("1 month", format=PCT),
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
title_col, about_col = st.columns([5, 1], vertical_alignment="center")
title_col.title("🛢️ Oil Tracker")
# A popover opens instantly in the browser (no page re-run). Its text is
# filled in at the bottom of this file.
about_popover = about_col.popover("ℹ️ How this works", width="stretch")
st.markdown("**When news like this happened before, what did oil do next?**")

latest_date, latest_price = prices.index[-1], prices.iloc[-1]
col1, col2, col3 = st.columns(3)
col1.metric("Brent crude (latest close)", f"${latest_price:.2f}",
            f"{(latest_price / prices.iloc[-6] - 1) * 100:+.1f}% over 5 trading days")
col2.metric("Events analysed",
            f"{len(opec_results) + len(inv_results) + len(fed_results):,}",
            f"{len(opec_results)} OPEC+ · {len(inv_results):,} EIA · {len(fed_results)} Fed",
            delta_color="off")
col3.metric("Price history", f"{prices.index[0].year}–{latest_date.year}",
            f"updated {latest_date:%b %d, %Y}", delta_color="off")

tab_bot, tab_cond, tab_lab, tab_inv, tab_opec, tab_fed = st.tabs(
    ["🤖 Paper trading bots", "🌡️ Market conditions", "🧪 Strategy lab",
     "📦 EIA weekly inventories", "🛢️ OPEC+ decisions", "🏦 Fed rate decisions"])

with tab_bot:
    bot_dashboard.render()

with tab_cond:
    conditions.render(features)

# ---------------------------------------------------------------------------
# Tab 0: Strategy lab - backtests of simple rules
# ---------------------------------------------------------------------------
with tab_lab:
    st.markdown("""
Each strategy is a simple rule that decides, at every day's close, whether to
**own oil or sit in cash**, using only information that was public by then.
We charge 0.10% every time it buys or sells. Rules were designed on
**2007–2016** and then checked on **2017–now**, a period they never saw.
A rule that only works in the first period was probably luck.
""")

    # What each rule says today
    today = features.iloc[-1]
    st.subheader(f"What each rule says now (as of {features.index[-1]:%b %d, %Y})")
    readings = {
        "trend_200d": f"Brent ${today['price']:.2f} vs 200-day avg ${today['sma200']:.2f}",
        "big_build_rebound": "Last report: " + inv.LABELS[inv_events.iloc[-1]["category"]],
        "tight_inventories": f"U.S. stocks {today['inv_vs_normal_pct']:+.1f}% vs normal",
        "crowded_short": f"Hedge-fund positioning at {today['mm_positioning_rank']:.0%} "
                         "of its 3-year range",
        "weak_dollar": f"Dollar {today['dollar_vs_50d_pct']:+.1f}% vs its 50-day avg",
    }
    cols = st.columns(len(readings))
    for col, (key, reading) in zip(cols, readings.items()):
        owns = bt_results[key]["position"].iloc[-1] > 0
        col.metric(strat.STRATEGIES[key][0], "Own oil" if owns else "Cash",
                   reading, delta_color="off")

    # Growth of $10,000
    st.subheader("Growth of $10,000")
    fig = go.Figure()
    for key, res in bt_results.items():
        equity = 10_000 * (1 + res["return"]).cumprod()
        fig.add_trace(go.Scatter(
            x=equity.index, y=equity.values, mode="lines",
            name=strat.STRATEGIES[key][0],
            line=dict(color=STRATEGY_COLORS[key],
                      width=1.5 if key == "buy_and_hold" else 2,
                      dash="dot" if key == "buy_and_hold" else "solid"),
            hovertemplate="$%{y:,.0f}"))
    fig.add_vline(x=pd.Timestamp(bt.SPLIT), line_color="#898781", line_dash="dot",
                  annotation_text="test period starts →", annotation_font_size=11,
                  annotation_font_color="#898781")
    fig.update_layout(height=470, margin=dict(l=10, r=10, t=30, b=10),
                      hovermode="x unified", yaxis_type="log",
                      yaxis_title="Value (log scale)", yaxis_tickprefix="$",
                      legend=dict(orientation="h", yanchor="top", y=-0.1, x=0))
    st.plotly_chart(fig, width="stretch", key="lab_equity")
    st.caption("Log scale: equal vertical distances = equal % gains. "
               "Based on Brent spot prices; real trading via futures or ETFs differs.")

    period = st.radio("Period", ["Test 2017-now", "Build 2007-2016"], horizontal=True,
                      key="lab_period")
    table = bt_metrics[bt_metrics["period"] == period].set_index("label")[
        ["annual_return_pct", "annual_volatility_pct", "sharpe", "max_drawdown_pct",
         "time_in_market_pct", "trades"]]
    st.dataframe(table, width="stretch", key="lab_table", column_config={
        "annual_return_pct": st.column_config.NumberColumn("Return / year", format=PCT),
        "annual_volatility_pct": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
        "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f",
            help="Return per unit of risk. Higher is better; above ~0.5 is decent."),
        "max_drawdown_pct": st.column_config.NumberColumn("Worst drop", format="%.1f%%"),
        "time_in_market_pct": st.column_config.NumberColumn("Time owning oil", format="%.0f%%"),
        "trades": st.column_config.NumberColumn("Trades"),
    })
    st.caption("Compare each rule with buy-and-hold in the same period. "
               "Research only: past results don't predict future ones. Not investment advice.")

# ---------------------------------------------------------------------------
# Tab 1: EIA weekly inventory reports
# ---------------------------------------------------------------------------
with tab_inv:
    latest = inv_events.iloc[-1]
    similar = inv_results[inv_results["category"] == latest["category"]]

    st.subheader(f"Latest report: {latest['date']:%A %b %d, %Y}")
    st.markdown(f"**{latest['description']}** - surprise of "
                f"**{latest['surprise_mb']:+.1f}M barrels** vs normal → "
                f"*{inv.LABELS[latest['category']]}*")
    c1, c2, c3 = st.columns(3)
    c1.metric("Similar past reports", f"{len(similar)}")
    c2.metric("Brent on report day: average", f"{similar['day_1_pct'].mean():+.2f}%")
    c3.metric("Brent rose on report day", f"{(similar['day_1_pct'] > 0).mean():.0%} of the time")

    st.markdown("""
Every Wednesday the EIA reports how much crude oil is stored in the U.S.
A **draw** (stocks falling) usually signals tight supply and tends to push
prices **up**; a **build** tends to push them **down**. We compare each week's
change with what is *normal for that time of year* (5-year average), because
stocks rise and fall with the seasons.
""")
    st.header("Average reaction by size of surprise")
    comparison_section(inv_results, inv_paths, "category", inv.CATEGORIES,
                       inv.LABELS, inv.COLORS, key="inv")

    st.header("Explore the reports")
    drilldown_section(inv_results, inv_paths, "category", inv.CATEGORIES,
                      inv.LABELS, inv.COLORS, key="inv", table_columns={
        "date": st.column_config.DateColumn("Report date", format="YYYY-MM-DD"),
        "change_mb": st.column_config.NumberColumn("Change (M bbl)", format="%+.1f"),
        "normal_mb": st.column_config.NumberColumn("Normal (M bbl)", format="%+.1f"),
        "surprise_mb": st.column_config.NumberColumn("Surprise (M bbl)", format="%+.1f"),
        **HORIZON_COLUMNS,
    })

# ---------------------------------------------------------------------------
# Tab 2: OPEC+ decisions
# ---------------------------------------------------------------------------
with tab_opec:
    st.header("Average reaction by decision type")
    comparison_section(opec_results, opec_paths, "decision", es.DECISIONS,
                       es.LABELS, es.COLORS, key="opec")

    st.header("Explore individual decisions")
    drilldown_section(opec_results, opec_paths, "decision", es.DECISIONS,
                      es.LABELS, es.COLORS, key="opec", table_columns={
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "size_mbd": st.column_config.NumberColumn("Size (mb/d)", format="%.2f"),
        **HORIZON_COLUMNS,
        "description": st.column_config.TextColumn("What happened", width="large"),
    })

# ---------------------------------------------------------------------------
# Fed rate decisions
# ---------------------------------------------------------------------------
with tab_fed:
    st.markdown("""
Every change in the Federal Reserve's target interest rate since 1990. Rate
moves affect oil through the economy (demand) and the dollar. We separate the
**first move of a new cycle** (a turn in policy, often a reaction to trouble or
a boom) from moves that **continue** a cycle. The Fed usually cuts when the economy
weakens and hikes when it's running hot, so these results largely reflect the
economy that prompted the decision.
""")
    st.header("Average reaction by type of rate change")
    comparison_section(fed_results, fed_paths, "decision", fed.CATEGORIES,
                       fed.LABELS, fed.COLORS, key="fed")

    st.header("Explore individual rate changes")
    drilldown_section(fed_results, fed_paths, "decision", fed.CATEGORIES,
                      fed.LABELS, fed.COLORS, key="fed", table_columns={
        "effective_date": st.column_config.DateColumn("Effective", format="YYYY-MM-DD"),
        "size_bp": st.column_config.NumberColumn("Change (bp)", format="%+d"),
        "new_rate": st.column_config.NumberColumn("New rate", format="%.2f%%"),
        **HORIZON_COLUMNS,
        "description": st.column_config.TextColumn("What happened", width="large"),
    })
    st.caption("Measured from the close two business days before the change took effect "
               "(the day before the announcement or earlier), so the reaction is never "
               "missed. Meetings where the Fed held rates aren't included.")

# ---------------------------------------------------------------------------
# "How this works" text, shown in the popover next to the title
# ---------------------------------------------------------------------------
with about_popover:
    st.markdown("""
### Data
- **Prices:** daily Brent crude spot prices from the U.S. EIA, via FRED.
- **Inventories:** EIA *Weekly U.S. Ending Stocks of Crude Oil* (excluding the
  Strategic Petroleum Reserve), reports since 2006.
- **OPEC+ decisions:** a hand-verified list of major decisions since 1999.
- **Positioning:** CFTC Commitments of Traders, "managed money" in NYMEX WTI.
- **Dollar:** Federal Reserve broad U.S. dollar index, via FRED.
- **Fed rate decisions:** the Fed's target rate (upper end of the range since
  2008), via FRED. Each change since 1990 is one event.
- **Bots:** live prices and the paper account from Alpaca.

### Market conditions
- Each indicator's reading is placed in one of five equal-sized buckets based on
  every trading day since 2007; we show Brent's average move over the next 20
  trading days for days in the same bucket.
- "Most similar days" compares all six indicators at once (each scaled by its
  normal range) and picks the 15 closest past days, at least 20 trading days apart.
- This is descriptive context, not a tested trading rule.

### Strategy backtests
- Each rule only uses data that was public at the time: inventory reports from
  their release day, CFTC positioning from the Monday after release, and the
  dollar index one week after its date.
- A position chosen at a day's close earns the next day's price change.
  0.10% is charged per buy or sell.
- Settings were fixed using 2007–2016; 2017–now is an out-of-sample test.
- Brent spot prices aren't directly tradable. Funds and futures that track oil
  have extra costs (e.g. rolling contracts), so real results would differ.

### Method
- **Starting point:** the closing price on the last trading day *before* each
  announcement - the last price set before anyone knew the news.
- **Inventory surprise:** the week's change minus the average change for the
  same week of the year over the previous 5 years. Professional traders compare
  against analyst forecasts instead, which aren't freely available, so this is
  an approximation.
- **Report dates:** assumed to be the Wednesday after the week ends (Thursday
  in weeks with a federal holiday). EIA occasionally moves other dates.

### Limits - please read
- **Markets react to surprises.** Expected news may barely move prices.
- **Small samples.** Some OPEC+ categories have only a handful of events; one
  extreme case (e.g. March 2020, during COVID) can dominate an average.
- **Other news happens at the same time.** Moves aren't caused only by the event.
- **Longer windows overlap.** A 1-month window after an inventory report contains
  three more reports, so 1-month inventory results are mostly noise.
- Past reactions don't guarantee future ones. **Not investment advice.**
""")
