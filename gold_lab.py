"""
"Popular gold rules, tested" (Research tab on /gold): five common beliefs
about gold ("buy when rates fall", "buy when the dollar weakens"...) turned
into simple own-gold-or-cash rules and tested on past prices the same way as
the oil site's Strategy lab (strategies.py, backtest.py). The page leads with
the verdict against simply holding gold, worked out from the results each
time, so it stays true as prices come in.

THE GOLDEN RULE (as for oil): on any day, a rule may only use what was public
by that day's close.
  - 10-year real interest rate (FRED DFII10): the Fed posts each day's rate
    late the next afternoon, after gold's close -> usable 2 business days later
  - Dollar index: published weekly by the Fed -> usable 7 days later
  - CFTC positioning: as of Tuesday, released Friday afternoon -> usable from
    the following Monday's close
  - News spikes (Media Cloud): a day's count is complete at midnight UTC ->
    usable from the NEXT trading day's close

The rules are the textbook ideas about what drives gold, written down BEFORE
looking at any results, and designed on 2007-2016 / tested on 2017-now like
the oil rules. Don't tune them by peeking at the 2017+ numbers.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import backtest as bt
import market_data as md
import news
import strategies as strat
import ui

HAVEN_TOPIC = "gold_haven"        # "Safe-haven rush (wars & crises)"


def build_features(prices: pd.Series, real_yield: pd.Series, timelines: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day with everything a gold rule may look at."""
    days = prices.index
    f = pd.DataFrame(index=days)
    f["price"] = prices
    f["sma200"] = prices.rolling(200).mean()
    f["trend_gap_pct"] = strat.trend_gap(prices)

    # Real interest rate vs its own 50-day average (negative = rates falling)
    real = real_yield.dropna()
    real_trend = real - real.rolling(50).mean()
    f["real_rate"] = strat._as_of(real, real.index + pd.offsets.BDay(2), days)
    f["real_vs_50d"] = strat._as_of(real_trend, real.index + pd.offsets.BDay(2), days)

    f["dollar_vs_50d_pct"] = strat.dollar_trend(md.load_dollar(), days)

    cot = md.load_cot("cot_gold")
    net = (cot["mm_long"] - cot["mm_short"]) / cot["open_interest"] * 100
    rank = net.rolling(156, min_periods=52).apply(lambda w: (w < w[-1]).mean(), raw=True)
    known = cot["report_date"] + pd.Timedelta(days=6)
    f["mm_positioning_rank"] = strat._as_of(rank, known, days)

    f["haven_news"] = None
    if not timelines.empty:
        spikes = news.all_spikes(timelines)
        spikes = spikes[spikes["topic"] == HAVEN_TOPIC]
        if len(spikes):
            usable = days.searchsorted(spikes["spike_day"], side="right")
            ok = usable < len(days)
            hit = pd.Series(True, index=days[usable[ok]])
            f["haven_news"] = hit[~hit.index.duplicated()].reindex(days)
        f.attrs["news_start"] = timelines["date"].min()
    return f


# The rules: each takes the features table and returns 1 (own gold) or 0 (cash) per day
def buy_and_hold(f):
    return pd.Series(1.0, index=f.index)


def trend_200d(f):
    gap = f["trend_gap_pct"]
    return (gap > 0).astype(float).where(gap.notna())


def falling_real_rates(f):
    """Own gold while the real interest rate is below its 50-day average:
    gold pays nothing, so it should do best when real rates are falling."""
    d = f["real_vs_50d"]
    return (d < 0).astype(float).where(d.notna())


def weak_dollar(f):
    d = f["dollar_vs_50d_pct"]
    return (d < 0).astype(float).where(d.notna())


def crowded_short(f):
    """Contrarian: own gold when hedge funds are more bearish than they've been
    75% of the time in the last 3 years."""
    rank = f["mm_positioning_rank"]
    return (rank <= 0.25).astype(float).where(rank.notna())


def haven_news(f, hold_days: int = 5):
    """After a safe-haven news spike (wars and crises), buy at the next close
    and hold for a week. News history starts in 2015."""
    position = f["haven_news"].notna().astype(float).rolling(hold_days, min_periods=1).max()
    start = f.attrs.get("news_start")
    return position.where(f.index >= start) if start is not None else position


STRATEGIES = {
    "buy_and_hold": ("Buy and hold (benchmark)", buy_and_hold, "#898781"),
    "trend_200d": ("Trend: above 200-day average", trend_200d, "#2a78d6"),
    "falling_real_rates": ("Falling real interest rates", falling_real_rates, "#1baf7a"),
    "weak_dollar": ("Weak dollar", weak_dollar, "#e87ba4"),
    "crowded_short": ("Hedge funds crowded short", crowded_short, "#eda100"),
    "haven_news": ("Safe-haven news", haven_news, "#6250d6"),
}


def run_all(f: pd.DataFrame):
    """Backtest every rule (same costs and periods as the oil lab)."""
    f = f[f.index >= bt.START]
    results, rows = {}, []
    for key, (label, rule, _) in STRATEGIES.items():
        res = bt.run(rule(f), f["price"])
        results[key] = res
        for period, part in [("Build 2007-2016", res[res.index < bt.SPLIT]),
                             ("Test 2017-now", res[res.index >= bt.SPLIT])]:
            rows.append({"strategy": key, "label": label, "period": period, **bt.metrics(part)})
    return results, pd.DataFrame(rows)


# Page: "Popular gold rules, tested" ---------------------------------------------
# Each rule is a belief people often repeat about gold, in plain words, and how we tested it
CLAIMS = {
    "trend_200d": ("“Buy gold when it's in an uptrend”",
                   "Owns gold while its price is above its average of the last 200 trading days."),
    "falling_real_rates": ("“Buy gold when interest rates fall”",
                           "Owns gold while the 10-year real interest rate (after inflation) is below its "
                           "50-day average."),
    "weak_dollar": ("“Buy gold when the dollar weakens”",
                    "Owns gold while the U.S. dollar index is below its 50-day average."),
    "crowded_short": ("“Buy gold when everyone else is bearish”",
                      "Owns gold when hedge funds are more pessimistic about gold than they've been 75% of "
                      "the time over the past 3 years (CFTC positioning)."),
    "haven_news": ("“Buy gold when war or crisis hits the news”",
                   "Buys the day after a news spike about wars and crises and holds for a week (news "
                   "history starts in 2015)."),
}
TEST = "Test 2017-now"


def render(results: dict, table: pd.DataFrame) -> None:
    test = table[table["period"] == TEST].set_index("strategy")
    hold = test.loc["buy_and_hold"]
    rules = test.drop(index="buy_and_hold")
    rules = rules[rules["trades"] > 0]
    beat = rules[rules["annual_return_pct"] > hold["annual_return_pct"]]
    safer = rules[rules["sharpe"] > hold["sharpe"]]
    best = rules["annual_return_pct"].idxmax()
    held = results["buy_and_hold"]
    grew = (1 + held.loc[held.index >= bt.SPLIT, "return"]).prod()

    st.subheader("Popular gold rules, tested", anchor=False)
    st.markdown("You'll often read that gold rises when interest rates fall, when the dollar weakens or when war "
                "breaks out. We turned five of these beliefs into simple rules that decide each day whether to "
                "**own gold or sit in cash**, using only what was public at the time, and compared each one with "
                "simply holding gold.")

    if beat.empty:
        headline = f"None of the {len(rules)} rules beat simply holding gold since 2017"
    else:
        headline = (f"{len(beat)} of the {len(rules)} rules beat simply holding gold since 2017: "
                    + ", ".join(CLAIMS[k][0] for k in beat.index))
    risk = ("None did better after allowing for risk either." if safer.empty else
            f"After allowing for risk, {len(safer)} did better: "
            + ", ".join(CLAIMS[k][0] for k in safer.index) + ".")
    with st.container(border=True):
        ui.eyebrow("The verdict")
        st.markdown(f"<div class='dialog-topic'>{headline}</div>", unsafe_allow_html=True)
        st.markdown(f"Holding gold returned **{hold['annual_return_pct']:.1f}% a year** from 2017 to now; the best "
                    f"rule, {CLAIMS[best][0]}, returned **{rules.loc[best, 'annual_return_pct']:.1f}%**. {risk}")
        st.markdown(f"**Why, most likely:** gold grew about **{grew:.1f}×** over that time, and a rule that spends "
                    "time in cash misses part of a rise like that. The signals these rules use (interest rates, "
                    "the dollar, the news) are also watched by every gold trader, so their effect is usually in "
                    "the price before an ordinary investor can act on it.")

    st.write("")
    st.markdown("**Each belief, 2017 to now**")
    cards = []
    for key, row in rules.iterrows():
        better = row["annual_return_pct"] > hold["annual_return_pct"]
        cards.append((CLAIMS[key][0], f"{row['annual_return_pct']:.1f}% a year",
                      f"vs {hold['annual_return_pct']:.1f}% holding gold · worst drop {row['max_drawdown_pct']:.0f}% "
                      f"(holding: {hold['max_drawdown_pct']:.0f}%) · owned gold {row['time_in_market_pct']:.0f}% "
                      "of the time", "#1d8a5e" if better else "#c43a39"))
    ui.kpi_row(cards, columns=3)
    if (rules["max_drawdown_pct"] > hold["max_drawdown_pct"] + 10).any():
        ui.tip("Some rules had much smaller worst drops, but only because they spent long stretches out of gold, "
               "and they earned less for it. A smaller drop alone doesn't make a rule better.", "Smaller drops?")

    st.write("")
    st.markdown("**Growth of $10,000**")
    fig = go.Figure()
    for key, res in results.items():
        equity = 10_000 * (1 + res["return"]).cumprod()
        is_hold = key == "buy_and_hold"
        fig.add_trace(go.Scatter(
            x=equity.index, y=equity.values, mode="lines",
            name="Holding gold" if is_hold else CLAIMS[key][0].strip("“”"),
            line=dict(color="#1d1d1b" if is_hold else STRATEGIES[key][2], width=2.6 if is_hold else 1.3),
            opacity=1 if is_hold else 0.75, hovertemplate="$%{y:,.0f}"))
    fig.add_vline(x=pd.Timestamp(bt.SPLIT), line_color=ui.MUTED, line_dash="dot")
    fig.add_annotation(x=pd.Timestamp(bt.SPLIT), y=0.02, yref="paper", yanchor="bottom", xanchor="left",
                       showarrow=False, text=" Test period →", font=dict(size=11, color=ui.MUTED))
    ui.base_layout(fig, 460, hovermode="x unified", yaxis_type="log", yaxis_title="Value (log scale)",
                   yaxis_tickprefix="$")
    fig.update_layout(margin=dict(l=8, r=8, t=60, b=8))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gold_lab_equity")
    ui.tip("The thick black line is simply holding gold. Log scale: equal vertical distances = equal % gains. "
           "Based on gold's price worked out from the GLD fund; owning GLD itself also costs its 0.40% yearly fee.")

    with st.expander("How the test works, and every number"):
        st.markdown(f"""
- **Fair rules.** Each rule only uses information public by that day's close: the real interest rate counts
  from two business days later, the dollar index from a week later, hedge-fund positioning from the Monday
  after its Friday release, and a day's news count from the next trading day.
- **Costs.** Every buy or sell costs {bt.COST_PCT:.2f}%.
- **No tuning.** The rules are the textbook versions, written down before any results were seen, and their
  settings were not adjusted afterwards. With enough tries, some setting always looks good on past prices
  by luck, and then fails.
- **Two periods.** 2007–2016 is shown for comparison; 2017–now is the main test.
""")
        for key, (claim, how) in CLAIMS.items():
            st.markdown(f"**{claim}**: {how}")
        results_table(table)
    st.caption("Not investment advice. Past results don't promise future ones, in either direction.")


@st.fragment
def results_table(table: pd.DataFrame) -> None:
    period = st.segmented_control("Period", [TEST, "Build 2007-2016"], default=TEST,
                                  key="gold_lab_period") or TEST
    shown = table[table["period"] == period]
    shown = shown[~((shown["strategy"] == "haven_news") & (shown["trades"] == 0))]
    shown = shown.assign(label=["Holding gold" if k == "buy_and_hold" else CLAIMS[k][0]
                                for k in shown["strategy"]])
    st.dataframe(shown.set_index("label")[["annual_return_pct", "annual_volatility_pct", "sharpe",
                                           "max_drawdown_pct", "time_in_market_pct", "trades"]],
                 width="stretch", key="gold_lab_table", column_config={
        "label": st.column_config.TextColumn("Rule"),
        "annual_return_pct": st.column_config.NumberColumn("Return / year", format=ui.PCT),
        "annual_volatility_pct": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
        "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f",
                                                help="Return per unit of risk. Higher is better; above ~0.5 is decent."),
        "max_drawdown_pct": st.column_config.NumberColumn("Worst drop", format="%.1f%%"),
        "time_in_market_pct": st.column_config.NumberColumn("Time owning gold", format="%.0f%%"),
        "trades": st.column_config.NumberColumn("Trades"),
    })


