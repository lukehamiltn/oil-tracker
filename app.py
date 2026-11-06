"""
Oil Tracker website.

Run it with:   streamlit run app.py
Then it opens in your browser at http://localhost:8501
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import fetch_prices

st.set_page_config(page_title="Oil Tracker", page_icon="🛢️", layout="wide")

HORIZON_NAMES = {1: "1 day", 5: "1 week (5 trading days)", 20: "1 month (20 trading days)"}


# ---------------------------------------------------------------------------
# Data - cached so the site doesn't redo the work on every click.
# ttl = refresh at most every 6 hours.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 60 * 60)
def get_data():
    if not es.DB_PATH.exists():
        fetch_prices.main()  # first run on a new machine: download prices
    prices = es.load_prices()
    results, paths = es.compute_results(prices, es.load_events())
    return prices, results, paths


prices, results, paths = get_data()


def pct(value: float) -> str:
    return f"{value:+.1f}%"


def style_chart(fig: go.Figure, y_title: str) -> go.Figure:
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    fig.add_vline(x=0, line_color="#898781", line_dash="dot", line_width=1,
                  annotation_text="close before announcement",
                  annotation_font_size=11, annotation_font_color="#898781")
    fig.update_layout(
        height=430, margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified",
        xaxis_title="Trading days from the close before the announcement",
        yaxis_title=y_title, yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0),
    )
    return fig


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🛢️ Oil Tracker")
st.markdown("**When OPEC+ made a decision like this before, what did oil do next?**")

latest_date, latest_price = prices.index[-1], prices.iloc[-1]
week_ago = prices.iloc[-6]
col1, col2, col3 = st.columns(3)
col1.metric("Brent crude (latest close)", f"${latest_price:.2f}",
            f"{(latest_price / week_ago - 1) * 100:+.1f}% over 5 trading days")
col2.metric("OPEC+ decisions analysed", len(results))
col3.metric("Price history", f"{prices.index[0].year}–{latest_date.year}",
            f"updated {latest_date:%b %d, %Y}", delta_color="off")

# ---------------------------------------------------------------------------
# Section 1: comparison of decision types
# ---------------------------------------------------------------------------
st.header("Average reaction by decision type")

fig = go.Figure()
for decision in es.DECISIONS:
    dates = results.loc[results["decision"] == decision, "date"]
    if dates.empty:
        continue
    avg = pd.concat([paths[d] for d in dates], axis=1).mean(axis=1)
    fig.add_trace(go.Scatter(
        x=avg.index, y=avg.values, mode="lines",
        name=f"{es.LABELS[decision]} ({len(dates)} events)",
        line=dict(color=es.COLORS[decision], width=2.5),
        hovertemplate="%{y:+.1f}%",
    ))
st.plotly_chart(style_chart(fig, "Average % change in Brent"), width="stretch")

horizon = st.radio("Measure the change after:", es.HORIZONS, index=2, horizontal=True,
                   format_func=lambda h: HORIZON_NAMES[h])
col = f"day_{horizon}_pct"

summary = (results.groupby("decision")[col]
           .agg(events="count", average="mean", median="median",
                pct_up=lambda s: (s > 0).mean() * 100, best="max", worst="min")
           .reindex(es.DECISIONS).dropna(how="all"))
summary.index = [es.LABELS[d] for d in summary.index]

st.dataframe(summary, width="stretch", column_config={
    "events": st.column_config.NumberColumn("Events"),
    "average": st.column_config.NumberColumn("Average", format="%+.1f%%"),
    "median": st.column_config.NumberColumn("Median", format="%+.1f%%"),
    "pct_up": st.column_config.NumberColumn("Times price rose", format="%.0f%%"),
    "best": st.column_config.NumberColumn("Best", format="%+.1f%%"),
    "worst": st.column_config.NumberColumn("Worst", format="%+.1f%%"),
})
st.caption(f"For comparison: on any ordinary day, Brent's typical move over "
           f"{HORIZON_NAMES[horizon]} is about ±{es.typical_move(prices, horizon):.1f}%. "
           "Results smaller than that may just be normal noise.")

# ---------------------------------------------------------------------------
# Section 2: drill into one decision type
# ---------------------------------------------------------------------------
st.header("Explore individual events")

decision = st.selectbox("Decision type", es.DECISIONS,
                        format_func=lambda d: es.LABELS[d])
group = results[results["decision"] == decision].sort_values("date", ascending=False)
color = es.COLORS[decision]

fig = go.Figure()
for _, event in group.iterrows():
    path = paths[event["date"]]
    fig.add_trace(go.Scatter(
        x=path.index, y=path.values, mode="lines", showlegend=False,
        line=dict(color=color, width=1), opacity=0.3,
        name=f"{event['date']:%Y-%m-%d}",
        hovertemplate=f"<b>{event['date']:%b %d, %Y}</b><br>"
                      f"{event['description']}<br>%{{y:+.1f}}%<extra></extra>",
    ))
avg = pd.concat([paths[d] for d in group["date"]], axis=1).mean(axis=1)
fig.add_trace(go.Scatter(x=avg.index, y=avg.values, mode="lines",
                         name="Average", line=dict(color=color, width=3.5),
                         hovertemplate="Average: %{y:+.1f}%<extra></extra>"))
fig = style_chart(fig, "% change in Brent")
fig.update_layout(hovermode="closest")
st.plotly_chart(fig, width="stretch")
st.caption("Thin lines are individual events; hover over one to see what it was. "
           "The thick line is the average.")

st.dataframe(
    group[["date", "size_mbd", "day_1_pct", "day_5_pct", "day_20_pct", "description"]],
    width="stretch", hide_index=True, column_config={
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "size_mbd": st.column_config.NumberColumn("Size (mb/d)", format="%.2f"),
        "day_1_pct": st.column_config.NumberColumn("1 day", format="%+.1f%%"),
        "day_5_pct": st.column_config.NumberColumn("1 week", format="%+.1f%%"),
        "day_20_pct": st.column_config.NumberColumn("1 month", format="%+.1f%%"),
        "description": st.column_config.TextColumn("What happened", width="large"),
    })

# ---------------------------------------------------------------------------
# Method & caveats
# ---------------------------------------------------------------------------
with st.expander("How this works, and its limits"):
    st.markdown("""
- **Prices:** daily Brent crude spot prices from the U.S. EIA, via FRED.
- **Starting point:** the closing price on the last trading day *before* each
  announcement - the last price set before anyone knew the decision.
- **Markets react to surprises.** A decision the market already expected may
  barely move the price, or move it the "wrong" way.
- **Small samples.** Some decision types have only a handful of events, and one
  extreme case (e.g. March 2020, during COVID) can dominate the average.
- **Other news happens at the same time.** These moves aren't caused only by OPEC+.
- Past reactions are not a guarantee of future ones. Not investment advice.
""")
