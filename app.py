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
import inventory_events as inv

st.set_page_config(page_title="Oil Tracker", page_icon="🛢️", layout="wide")

HORIZON_NAMES = {1: "1 day", 5: "1 week (5 trading days)", 20: "1 month (20 trading days)"}
PCT = "%+.1f%%"


# ---------------------------------------------------------------------------
# Data - cached so the site doesn't redo the work on every click.
# ttl = refresh at most every 6 hours (downloads fresh data each time).
# ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 60 * 60, show_spinner="Loading the latest oil data...")
def get_data():
    fetch_prices.main()
    inv.download_inventories()
    prices = es.load_prices()
    opec = es.compute_results(prices, es.load_events())
    inv_events = inv.build_events(inv.load_inventories())
    inventory = es.compute_results(prices, inv_events)
    return prices, opec, inventory, inv_events


prices, (opec_results, opec_paths), (inv_results, inv_paths), inv_events = get_data()


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
st.title("🛢️ Oil Tracker")
st.markdown("**When news like this happened before, what did oil do next?**")

latest_date, latest_price = prices.index[-1], prices.iloc[-1]
col1, col2, col3 = st.columns(3)
col1.metric("Brent crude (latest close)", f"${latest_price:.2f}",
            f"{(latest_price / prices.iloc[-6] - 1) * 100:+.1f}% over 5 trading days")
col2.metric("Events analysed", f"{len(opec_results) + len(inv_results):,}",
            f"{len(opec_results)} OPEC+ · {len(inv_results):,} EIA reports",
            delta_color="off")
col3.metric("Price history", f"{prices.index[0].year}–{latest_date.year}",
            f"updated {latest_date:%b %d, %Y}", delta_color="off")

tab_inv, tab_opec, tab_about = st.tabs(
    ["📦 EIA weekly inventories", "🛢️ OPEC+ decisions", "ℹ️ How this works"])

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
# Tab 3: Method & caveats
# ---------------------------------------------------------------------------
with tab_about:
    st.markdown("""
### Data
- **Prices:** daily Brent crude spot prices from the U.S. EIA, via FRED.
- **Inventories:** EIA *Weekly U.S. Ending Stocks of Crude Oil* (excluding the
  Strategic Petroleum Reserve), reports since 2006.
- **OPEC+ decisions:** a hand-verified list of major decisions since 1999.

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
