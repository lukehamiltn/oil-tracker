"""
Market conditions: where does each indicator stand today versus history,
and what did Brent do next when things looked similar?

Two views:
  1. One indicator at a time - today's reading is put into one of five equal
     buckets ("very low" ... "very high") based on history since 2007, and we
     show Brent's average move over the following month in that bucket.
  2. All indicators together - the past days that looked MOST like today
     ("analogs"), and what Brent did over the month after each.

This is description, not a trading rule: the bucket edges use the whole
history, and neighbouring days overlap, so treat the numbers as context.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui

START = "2007-01-01"
HORIZON = 20                 # trading days ahead (~1 month)
N_ANALOGS = 15
MIN_GAP = 20                 # analog days must be >= 20 trading days apart

INDICATORS = {
    "trend_gap_pct": ("Brent vs its 200-day average", "%+.1f%%",
                      "Above = uptrend; far above can mean stretched."),
    "momentum_3m_pct": ("Brent change over 3 months", "%+.1f%%",
                        "Recent direction and strength of the move."),
    "volatility_1m_pct": ("Volatility (last month, yearly rate)", "%.0f%%",
                          "How violently prices are swinging."),
    "inv_vs_normal_pct": ("U.S. crude stocks vs normal", "%+.1f%%",
                          "Below normal = tight supply."),
    "positioning_pct": ("Hedge-fund positioning (3-yr range)", "%.0f%%",
                        "0% = most bearish in 3 years, 100% = most bullish."),
    "dollar_vs_50d_pct": ("Dollar vs its 50-day average", "%+.1f%%",
                          "A weaker dollar has tended to help oil."),
}
BUCKETS = ["Very low", "Low", "Middle", "High", "Very high"]


def build_table(features: pd.DataFrame) -> pd.DataFrame:
    """Indicators for every day, plus Brent's change over the NEXT month."""
    price = features["price"]
    t = pd.DataFrame(index=features.index)
    t["trend_gap_pct"] = features["trend_gap_pct"]
    t["momentum_3m_pct"] = (price / price.shift(63) - 1) * 100
    t["volatility_1m_pct"] = price.pct_change(fill_method=None).rolling(20).std() * np.sqrt(252) * 100
    t["inv_vs_normal_pct"] = features["inv_vs_normal_pct"]
    t["positioning_pct"] = features["mm_positioning_rank"] * 100
    t["dollar_vs_50d_pct"] = features["dollar_vs_50d_pct"]
    t["next_month_pct"] = (price.shift(-HORIZON) / price - 1) * 100
    return t[t.index >= START]


def indicator_summary(table: pd.DataFrame) -> pd.DataFrame:
    today = table.iloc[-1]
    history = table.dropna(subset=["next_month_pct"])
    rows = []
    for col, (label, _, _) in INDICATORS.items():
        values = table[col].dropna()
        # Rank first so tied values can't make two bucket edges identical
        buckets = pd.qcut(values.rank(method="first"), 5, labels=BUCKETS)
        today_bucket = buckets.iloc[-1]
        same = history.loc[history.index.intersection(buckets[buckets == today_bucket].index)]
        rows.append({
            "indicator": label, "key": col, "today": today[col],
            "percentile": (values < today[col]).mean() * 100,
            "bucket": today_bucket,
            "days": len(same),
            "avg_next_month": same["next_month_pct"].mean(),
            "pct_up": (same["next_month_pct"] > 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def find_analogs(table: pd.DataFrame) -> pd.DataFrame:
    """The past days most similar to today across all indicators."""
    cols = list(INDICATORS)
    data = table[cols].dropna()
    z = (data - data.mean()) / data.std()           # put indicators on one scale
    distance = np.sqrt(((z - z.iloc[-1]) ** 2).sum(axis=1))
    # Only days whose following month is complete and not overlapping today
    candidates = distance.iloc[:-(HORIZON + 40)].sort_values()
    chosen = []
    for day in candidates.index:
        position = data.index.get_loc(day)
        if all(abs(position - data.index.get_loc(c)) >= MIN_GAP for c in chosen):
            chosen.append(day)
        if len(chosen) == N_ANALOGS:
            break
    out = table.loc[chosen, cols + ["next_month_pct"]].copy()
    out["similarity"] = 1 / (1 + distance.loc[chosen])
    return out


def render(features: pd.DataFrame) -> None:
    table = build_table(features)
    as_of = table.index[-1]
    history = table.dropna(subset=["next_month_pct"])
    base_avg = history["next_month_pct"].mean()
    base_up = (history["next_month_pct"] > 0).mean() * 100

    ui.eyebrow("Market conditions")
    st.subheader("How today's market compares with history", anchor=False)
    st.markdown(f"""
Where does the oil market stand **today** compared with every trading day since 2007,
and what did Brent do over the **following month** when conditions were similar?
For reference, across all days Brent's average move over the next month was
**{base_avg:+.1f}%**, and it rose **{base_up:.0f}%** of the time.
""")

    # --- 1. Indicator by indicator ------------------------------------------
    st.markdown(f"**Today's readings** (as of {as_of:%b %d, %Y})")
    summary = indicator_summary(table)
    cols = st.columns(3)
    for i, row in summary.iterrows():
        label, fmt, help_text = INDICATORS[row["key"]]
        cols[i % 3].metric(label, fmt % row["today"],
                           f"{row['bucket']} · higher than {row['percentile']:.0f}% of days",
                           delta_color="off", help=help_text, border=True)

    st.markdown("**What Brent did over the next month, when each indicator was in today's bucket**")
    st.dataframe(
        summary[["indicator", "bucket", "days", "avg_next_month", "pct_up"]],
        width="stretch", hide_index=True, key="cond_table", column_config={
            "indicator": st.column_config.TextColumn("Indicator"),
            "bucket": st.column_config.TextColumn("Today's bucket"),
            "days": st.column_config.NumberColumn("Past days in bucket"),
            "avg_next_month": st.column_config.NumberColumn("Avg next month", format="%+.1f%%"),
            "pct_up": st.column_config.NumberColumn("Times Brent rose", format="%.0f%%"),
        })
    st.caption(f"Compare each row with the all-days figures above ({base_avg:+.1f}%, "
               f"rose {base_up:.0f}% of the time). Days next to each other overlap heavily, "
               "so 'past days' overstates how much independent evidence there is.")

    # --- 2. Closest past situations -------------------------------------------
    st.write(""); st.markdown("**Past situations most like today**")
    analogs = find_analogs(table)
    a_avg = analogs["next_month_pct"].mean()
    a_up = (analogs["next_month_pct"] > 0).mean() * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Closest matches used", f"{len(analogs)}",
              f"at least {MIN_GAP} trading days apart", delta_color="off", border=True)
    c2.metric("Brent over their next month: average", f"{a_avg:+.1f}%",
              f"median {analogs['next_month_pct'].median():+.1f}%", delta_color="off", border=True)
    c3.metric("Brent rose afterwards", f"{a_up:.0f}% of the time",
              f"all days: {base_up:.0f}%", delta_color="off", border=True)

    # Price path after each analog
    price = features["price"]
    fig = go.Figure()
    paths = []
    for day in analogs.index:
        pos = price.index.get_loc(day)
        path = (price.iloc[pos:pos + HORIZON + 1].values / price.iloc[pos] - 1) * 100
        paths.append(path)
        fig.add_trace(go.Scatter(
            x=list(range(len(path))), y=path, mode="lines", showlegend=False,
            line=dict(color="#2a78d6", width=1), opacity=0.35,
            hovertemplate=f"<b>{day:%b %d, %Y}</b><br>%{{y:+.1f}}%<extra></extra>"))
    avg_path = np.mean(paths, axis=0)
    fig.add_trace(go.Scatter(x=list(range(len(avg_path))), y=avg_path, mode="lines",
                             name="Average of matches", line=dict(color="#2a78d6", width=3.5),
                             hovertemplate="Average: %{y:+.1f}%<extra></extra>"))
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                      hovermode="closest", yaxis_ticksuffix="%",
                      xaxis_title="Trading days after the matching day",
                      yaxis_title="% change in Brent",
                      legend=dict(orientation="h", yanchor="top", y=-0.18, x=0))
    st.plotly_chart(fig, width="stretch", key="cond_analogs")
    st.caption("Each thin line is one past day that looked like today. Hover to see which.")

    show = analogs.reset_index(names="date").sort_values("similarity", ascending=False)
    config = {
        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
        "similarity": st.column_config.ProgressColumn("Similarity", format="%.2f",
                                                      min_value=0, max_value=1),
        "next_month_pct": st.column_config.NumberColumn("Brent next month", format="%+.1f%%"),
    }
    for col, (label, fmt, _) in INDICATORS.items():
        config[col] = st.column_config.NumberColumn(label, format=fmt)
    st.dataframe(show[["date", "similarity", "next_month_pct", *INDICATORS]],
                 width="stretch", hide_index=True, key="cond_analog_table",
                 column_config=config)
    st.caption("Similarity compares all six indicators at once, each scaled to its "
               "normal range. History rhymes but doesn't repeat. Not investment advice.")
