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

The gas and gold pages use the same views with their own indicators (GAS,
gas_table; GOLD, gold_table).
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

# Short column names for the table of similar past days (full names on hover)
SHORT = {"trend_gap_pct": "vs 200-day", "momentum_3m_pct": "3-month change",
         "volatility_1m_pct": "Volatility", "inv_vs_normal_pct": "Stocks vs normal",
         "positioning_pct": "Hedge funds", "dollar_vs_50d_pct": "Dollar vs 50-day"}

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

# What changes between markets: the price's name, the indicators, wording
OIL = {
    "key": "cond", "name": "Brent", "market": "the oil market", "indicators": INDICATORS, "short": SHORT,
    "recent_tip": "the price readings use Brent futures, scaled to meet the spot price on the last official "
                  "day. Inventories, hedge-fund positioning and the dollar come from their own weekly reports.",
}

GAS_INDICATORS = {
    "trend_gap_pct": ("Henry Hub vs its 200-day average", "%+.1f%%",
                      "Above = uptrend; far above can mean stretched."),
    "momentum_3m_pct": ("Henry Hub change over 3 months", "%+.1f%%",
                        "Recent direction and strength of the move."),
    "volatility_1m_pct": ("Volatility (last month, yearly rate)", "%.0f%%",
                          "How violently prices are swinging. Gas is usually much wilder than oil."),
    "storage_vs_5yr_pct": ("Gas in storage vs the 5-year average", "%+.1f%%",
                           "For the same week of the year. Below = tight supply, above = plenty."),
    "yoy_pct": ("Henry Hub vs a year ago", "%+.1f%%",
                "Compares with the same season last year, so the winter/summer swing cancels out."),
}
GAS = {
    "key": "gas_cond", "name": "Henry Hub", "market": "the natural gas market", "indicators": GAS_INDICATORS,
    "short": {"trend_gap_pct": "vs 200-day", "momentum_3m_pct": "3-month change", "volatility_1m_pct": "Volatility",
              "storage_vs_5yr_pct": "Storage vs 5-yr", "yoy_pct": "vs a year ago"},
    # Gas spot prices have rare huge spikes (a cold snap can triple them), so
    # the typical (median) match is shown instead of the average
    "middle": "median",
    "recent_tip": "the price readings use Henry Hub futures, scaled to meet the spot price on the last official "
                  "day. Storage comes from the weekly EIA report.",
}


GOLD_INDICATORS = {
    "trend_gap_pct": ("Gold vs its 200-day average", "%+.1f%%",
                      "Above = uptrend; far above can mean stretched."),
    "momentum_3m_pct": ("Gold change over 3 months", "%+.1f%%",
                        "Recent direction and strength of the move."),
    "volatility_1m_pct": ("Volatility (last month, yearly rate)", "%.0f%%",
                          "How violently prices are swinging. Gold is usually calmer than oil."),
    "real_yield": ("10-year real interest rate", "%.2f%%",
                   "Interest after inflation, on inflation-protected Treasuries. Gold pays none, so high real "
                   "rates have usually weighed on it."),
    "real_yield_3m": ("Real rate change over 3 months", "%+.2f pts",
                      "Rising real rates have usually been bad for gold; falling ones good."),
    "dollar_vs_50d_pct": ("Dollar vs its 50-day average", "%+.1f%%",
                          "Gold is priced in dollars: a weaker dollar has tended to help it."),
}
GOLD = {
    "key": "gold_cond", "name": "Gold", "market": "the gold market", "indicators": GOLD_INDICATORS,
    "short": {"trend_gap_pct": "vs 200-day", "momentum_3m_pct": "3-month change", "volatility_1m_pct": "Volatility",
              "real_yield": "Real rate", "real_yield_3m": "Real rate, 3-mo change",
              "dollar_vs_50d_pct": "Dollar vs 50-day"},
    "recent_tip": "the price readings use gold futures, scaled to meet the GLD-based price on the last official "
                  "day. The real interest rate and the dollar come from the Federal Reserve (FRED).",
}


def _price_columns(t: pd.DataFrame, price: pd.Series) -> None:
    t["trend_gap_pct"] = (price / price.rolling(200).mean() - 1) * 100
    t["momentum_3m_pct"] = (price / price.shift(63) - 1) * 100
    t["volatility_1m_pct"] = price.pct_change(fill_method=None).rolling(20).std() * np.sqrt(252) * 100
    t["next_month_pct"] = (price.shift(-HORIZON) / price - 1) * 100


def gas_table(prices: pd.Series, storage_vs_5yr: pd.Series) -> pd.DataFrame:
    """Gas indicators for every trading day, plus Henry Hub's change over the
    NEXT month. `storage_vs_5yr` is dated by when each report came out, so a
    day only knows the storage reports published by then."""
    price = prices.dropna()
    t = pd.DataFrame(index=price.index)
    _price_columns(t, price)
    t["yoy_pct"] = (price / price.shift(252) - 1) * 100
    t["storage_vs_5yr_pct"] = storage_vs_5yr.reindex(t.index.union(storage_vs_5yr.index)).ffill().reindex(t.index)
    t = t[list(GAS_INDICATORS) + ["next_month_pct"]]
    return t.dropna(subset=list(GAS_INDICATORS))


def gold_table(prices: pd.Series, real_yield: pd.Series, dollar: pd.Series) -> pd.DataFrame:
    """Gold indicators for every trading day, plus gold's change over the NEXT
    month. The real rate and the dollar are carried forward to each gold day
    (they are published a day or more later)."""
    price = prices.dropna()
    t = pd.DataFrame(index=price.index)
    _price_columns(t, price)

    def on_gold_days(series: pd.Series) -> pd.Series:
        return series.reindex(t.index.union(series.index)).ffill().reindex(t.index)
    t["real_yield"] = on_gold_days(real_yield)
    t["real_yield_3m"] = t["real_yield"] - t["real_yield"].shift(63)
    usd = on_gold_days(dollar)
    t["dollar_vs_50d_pct"] = (usd / usd.rolling(50).mean() - 1) * 100
    t = t[list(GOLD_INDICATORS) + ["next_month_pct"]]
    return t.dropna(subset=list(GOLD_INDICATORS))


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


def indicator_summary(table: pd.DataFrame, indicators: dict = INDICATORS, center: str = "mean") -> pd.DataFrame:
    today = table.iloc[-1]
    history = table.dropna(subset=["next_month_pct"])
    rows = []
    for col, (label, _, _) in indicators.items():
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
            "avg_next_month": same["next_month_pct"].median() if center == "median" else same["next_month_pct"].mean(),
            "pct_up": (same["next_month_pct"] > 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def find_analogs(table: pd.DataFrame, indicators: dict = INDICATORS) -> pd.DataFrame:
    """The past days most similar to today across all indicators."""
    cols = list(indicators)
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


def render(features: pd.DataFrame, recent_days: int = 0) -> None:
    """The oil page's view. recent_days: how many of the latest days come from
    futures prices (the official spot prices are published about a week late)."""
    show(build_table(features), features["price"], recent_days, OIL)


def show(table: pd.DataFrame, price: pd.Series, recent_days: int, spec: dict) -> None:
    """Both views for one market. `spec`: OIL or GAS."""
    name, indicators, short, key = spec["name"], spec["indicators"], spec["short"], spec["key"]
    since = table.index[0].year
    as_of = table.index[-1]
    history = table.dropna(subset=["next_month_pct"])
    typical = spec.get("middle") == "median"
    base_avg = history["next_month_pct"].median() if typical else history["next_month_pct"].mean()
    middle_word = "typical" if typical else "average"
    base_up = (history["next_month_pct"] > 0).mean() * 100

    st.subheader("Today against history", anchor=False)
    st.markdown(f"""
Where does {spec['market']} stand **today** compared with every trading day since {since},
and what did {name} do over the **following month** when conditions were similar?
For reference, across all days {name}'s {middle_word} move over the next month was
**{base_avg:+.1f}%**, and it rose **{base_up:.0f}%** of the time.
""")

    # --- 1. Indicator by indicator ------------------------------------------
    st.markdown(f"**Today's readings** (as of {ui.day(as_of)})")
    if recent_days:
        official = table.index[-1 - recent_days]
        ui.tip(f"Official daily spot prices are published about a week late (latest "
               f"{ui.day(official, year=False)}). For the {recent_days} trading days since, "
               + spec["recent_tip"], "About today's prices")
    summary = indicator_summary(table, indicators, spec.get("middle", "mean"))
    cards = []
    for _, row in summary.iterrows():
        label, fmt, help_text = indicators[row["key"]]
        title = (f'<span class="note-wrap" tabindex="0">{label}'
                 f'<span class="note-tip">{help_text}</span></span>')
        note = (f'<span class="bucket">{row["bucket"]} · higher than {row["percentile"]:.0f}% '
                f'of days</span><div class="kpi-after">Past days like this: {name} {"typically " if typical else ""}'
                f'<b>{row["avg_next_month"]:+.1f}%</b> the next month, rose '
                f'{row["pct_up"]:.0f}% of the time</div>')
        cards.append((title, fmt % row["today"], note, None))
    ui.kpi_row(cards, columns=3)
    ui.tip(f"Each card puts today's reading in one of five buckets (very low to very high) "
           f"and shows what {name} did over the next month on past days in the same bucket. "
           f"Compare with all days: {base_avg:+.1f}%, rose {base_up:.0f}% of the time. Days "
           "next to each other overlap heavily, so these are weaker evidence than they look.")

    # --- 2. Closest past situations -------------------------------------------
    st.write(""); st.markdown("**Past situations most like today**")
    analogs = find_analogs(table, indicators)
    a_avg = analogs["next_month_pct"].mean()
    a_up = (analogs["next_month_pct"] > 0).mean() * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Closest matches used", f"{len(analogs)}",
              f"at least {MIN_GAP} trading days apart", delta_color="off", delta_arrow="off", border=True)
    a_median = analogs["next_month_pct"].median()
    if spec.get("middle") == "median":
        c2.metric(f"{name} over their next month: typical", f"{a_median:+.1f}%",
                  f"median; average {a_avg:+.1f}%", delta_color="off", delta_arrow="off", border=True)
    else:
        c2.metric(f"{name} over their next month: average", f"{a_avg:+.1f}%",
                  f"median {a_median:+.1f}%", delta_color="off", delta_arrow="off", border=True)
    c3.metric(f"{name} rose afterwards", f"{a_up:.0f}% of the time",
              f"all days: {base_up:.0f}%", delta_color="off", delta_arrow="off", border=True)

    # Price path after each analog
    paths = []
    for day in analogs.index:
        pos = price.index.get_loc(day)
        paths.append((price.iloc[pos:pos + HORIZON + 1].values / price.iloc[pos] - 1) * 100)
    width = min(len(p) for p in paths)
    paths = np.array([p[:width] for p in paths])
    x = list(range(width))
    low, high = np.percentile(paths, 25, axis=0), np.percentile(paths, 75, axis=0)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x + x[::-1], y=list(high) + list(low[::-1]), fill="toself",
                             fillcolor="rgba(42,120,214,0.15)", line=dict(width=0),
                             name="Middle half of matches", hoverinfo="skip"))
    typical = spec.get("middle") == "median"
    fig.add_trace(go.Scatter(x=x, y=np.median(paths, axis=0) if typical else paths.mean(axis=0), mode="lines",
                             name="Typical match (median)" if typical else "Average of matches",
                             line=dict(color="#1f4e8c", width=3),
                             hovertemplate="Day %{x}: %{y:+.1f}%<extra></extra>"))
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    ui.base_layout(fig, 360, hovermode="x unified", yaxis_ticksuffix="%",
                   xaxis_title="Trading days after the matching day",
                   yaxis_title=f"% change in {name}")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"{key}_analogs")
    ui.tip(f"The line is the {'typical (median)' if typical else 'average'} path after the past days most like today; the shaded "
           "band holds the middle half of them. Each one is listed in the table below.")

    rows = analogs.reset_index(names="date").sort_values("similarity", ascending=False)
    config = {
        "date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
        "similarity": st.column_config.ProgressColumn("Similarity", format="%.2f",
                                                      min_value=0, max_value=1),
        "next_month_pct": st.column_config.NumberColumn(f"{name} next month", format="%+.1f%%"),
    }
    for col, (label, fmt, _) in indicators.items():
        config[col] = st.column_config.NumberColumn(short[col], format=fmt, help=label)
    st.dataframe(rows[["date", "similarity", "next_month_pct", *indicators]],
                 width="stretch", hide_index=True, key=f"{key}_analog_table",
                 column_config=config)
    ui.tip(f"Similarity compares all {len(indicators)} indicators at once, each scaled to its "
           "normal range.")
