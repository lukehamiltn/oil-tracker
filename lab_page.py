"""The Strategy lab page: backtests of simple trading rules."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import backtest as bt
import inventory_events as inv
import strategies as strat
import ui

STRATEGY_COLORS = {"buy_and_hold": "#898781", "trend_200d": "#2a78d6",
                   "big_build_rebound": "#eb6834", "tight_inventories": "#1baf7a",
                   "crowded_short": "#eda100", "weak_dollar": "#e87ba4"}


def render(features, bt_results, bt_metrics, inv_events) -> None:
    st.subheader("Testing simple trading rules", anchor=False)
    st.markdown(f"""
Each rule decides at every day's close whether to **own oil or sit in cash**, using
only information that was public by then, and pays {bt.COST_PCT:.2f}% per trade.
Rules were designed on **2007–2016**, then tested on **2017–now**, a period they
never saw. A rule that only works in the first period was probably luck.
""")

    today = features.iloc[-1]
    st.markdown(f"**What each rule says now** (as of {features.index[-1]:%b %d, %Y})")
    readings = {
        "trend_200d": f"Brent ${today['price']:.2f} vs 200-day avg ${today['sma200']:.2f}",
        "big_build_rebound": "Last report: " + inv.LABELS[inv_events.iloc[-1]["category"]],
        "tight_inventories": f"U.S. stocks {today['inv_vs_normal_pct']:+.1f}% vs normal",
        "crowded_short": f"Hedge-fund positioning at {today['mm_positioning_rank']:.0%} "
                         "of its 3-year range",
        "weak_dollar": f"Dollar {today['dollar_vs_50d_pct']:+.1f}% vs its 50-day avg",
    }
    ui.kpi_row([(strat.STRATEGIES[key][0],
                 "Own oil" if bt_results[key]["position"].iloc[-1] > 0 else "Cash",
                 reading, None) for key, reading in readings.items()], columns=len(readings))

    st.write("")
    st.markdown("**Growth of $10,000**")
    fig = go.Figure()
    for key, res in bt_results.items():
        equity = 10_000 * (1 + res["return"]).cumprod()
        fig.add_trace(go.Scatter(
            x=equity.index, y=equity.values, mode="lines", name=strat.STRATEGIES[key][0],
            line=dict(color=STRATEGY_COLORS[key],
                      width=1.5 if key == "buy_and_hold" else 2,
                      dash="dot" if key == "buy_and_hold" else "solid"),
            hovertemplate="$%{y:,.0f}"))
    fig.add_vline(x=pd.Timestamp(bt.SPLIT), line_color=ui.MUTED, line_dash="dot",
                  annotation_text="test period starts →", annotation_font_size=11,
                  annotation_font_color=ui.MUTED)
    ui.base_layout(fig, 460, hovermode="x unified", yaxis_type="log",
                   yaxis_title="Value (log scale)", yaxis_tickprefix="$")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="lab_equity")
    st.caption("Log scale: equal vertical distances = equal % gains. Based on Brent spot "
               "prices; trading through funds or futures differs.")
    results_table(bt_metrics)


@st.fragment
def results_table(bt_metrics) -> None:
    period = st.segmented_control("Period", ["Test 2017-now", "Build 2007-2016"],
                                  default="Test 2017-now", key="lab_period") or "Test 2017-now"
    table = bt_metrics[bt_metrics["period"] == period].set_index("label")[
        ["annual_return_pct", "annual_volatility_pct", "sharpe", "max_drawdown_pct",
         "time_in_market_pct", "trades"]]
    st.dataframe(table, width="stretch", key="lab_table", column_config={
        "label": st.column_config.TextColumn("Rule"),
        "annual_return_pct": st.column_config.NumberColumn("Return / year", format=ui.PCT),
        "annual_volatility_pct": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
        "sharpe": st.column_config.NumberColumn(
            "Sharpe", format="%.2f",
            help="Return per unit of risk. Higher is better; above ~0.5 is decent."),
        "max_drawdown_pct": st.column_config.NumberColumn("Worst drop", format="%.1f%%"),
        "time_in_market_pct": st.column_config.NumberColumn("Time owning oil", format="%.0f%%"),
        "trades": st.column_config.NumberColumn("Trades"),
    })
    st.caption("Compare each rule with buy-and-hold over the same period.")
