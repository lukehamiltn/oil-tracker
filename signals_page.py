"""The Market signals tab: the futures curve, Brent minus WTI, and the
refining margin, each with a plain reading of what it says today.
Calculations are in signals.py."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import live_prices
import signals as sg
import ui

NAVY = "#1f3a5f"
PAST = {"1 month ago": "#9a988f", "3 months ago": "#c9c7bd"}


@st.cache_data(ttl=30 * 60, show_spinner=False)
def _curve(market: str, hour: str) -> pd.DataFrame:
    return sg.curve(market)            # shared by all visitors, refreshed every 30 min


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _spreads(_markets: dict, last_day: str) -> pd.DataFrame:
    """Official prices carried to today with scaled futures (live_prices.extend)."""
    ext = {}
    for key in ("BRENT", "WTI", "GASOLINE", "HEATING_OIL"):
        try:
            ext[key] = live_prices.extend(_markets[key], key)[0]
        except Exception:
            ext[key] = _markets[key]
    return sg.spreads(ext["BRENT"], ext["WTI"], ext["GASOLINE"], ext["HEATING_OIL"])


def render(data: dict) -> None:
    st.subheader("Market signals", anchor=False)
    st.caption("Three prices that say more about the oil market than the price alone: whether "
               "oil is scarce right now, how world oil compares with U.S. oil, and how much "
               "refiners earn making fuel.")
    m = data["markets"]
    hour = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H")
    brent_curve = _curve("BRENT", hour)
    shape = sg.curve_shape(brent_curve)
    table = _spreads(m, str(m["BRENT"].index[-1]))
    bw, margin = sg.standing(table["brent_wti"]), sg.standing(table["margin"])

    cards = []
    if shape:
        cards.append(("Brent futures curve", shape["shape"].capitalize(),
                      curve_note(shape), None))
    cards.append(("Brent minus WTI", f"${bw['now']:.2f}",
                  f"{sg.level_word(bw['pct_below'])} · typical ${bw['low']:.0f}–"
                  f"{bw['high']:.0f} since 2015", None))
    cards.append(("Refining margin", f"${margin['now']:.2f}",
                  f"per barrel · {sg.level_word(margin['pct_below'])} · typical "
                  f"${margin['low']:.0f}–{margin['high']:.0f} since 2015", None))
    ui.kpi_row(cards, columns=len(cards))
    st.write("")

    curve_section(brent_curve, hour)
    st.divider()
    gap_section(
        table["brent_wti"], bw, "brent_wti",
        "Brent minus WTI: world oil vs U.S. oil",
        "#2a78d6",
        bw_reading(bw),
        "Brent is priced in the North Sea and is the benchmark for most of the world's oil; "
        "WTI is priced in Oklahoma and is the U.S. benchmark. Brent is usually a few dollars "
        "dearer because U.S. oil must be shipped to reach world buyers. The gap widens when "
        "the world market is tighter than the U.S. one (trouble in the Middle East, "
        "sanctions on exporters) or when U.S. pipelines and ports are full, and narrows when "
        "the U.S. is short of oil.")
    st.divider()
    gap_section(
        table["margin"], margin, "margin",
        "Refining margin: what refiners earn per barrel",
        "#a8282a",
        margin_reading(margin),
        "Also called the 3-2-1 crack spread: refineries turn about 3 barrels of crude into 2 "
        "of gasoline and 1 of diesel. The margin is the value of that fuel (New York Harbor "
        "prices) minus the cost of 3 barrels of Brent, per barrel of crude. It isn't any "
        "one company's profit, which also depends on running costs. High margins mean fuel "
        "is scarce next to crude, so refiners run harder and buy more crude.")
    ui.tip("Official spot prices arrive about a week late; the last few days are filled in "
           "with futures prices, scaled to meet the official price (as elsewhere on the "
           "site). Futures curves are about 10 minutes delayed. 'Typical' is the middle 80% "
           "of trading days since 2015.", "Where these numbers come from")


def curve_note(shape: dict) -> str:
    when = f"{shape['front_month']:%b %Y} vs {shape['later_month']:%b %Y}"
    if shape["shape"] == "backwardation":
        return f"oil now ${shape['gap']:.2f} ({shape['gap_pct']:.0f}%) dearer than a year out · {when}"
    if shape["shape"] == "contango":
        return f"oil now ${-shape['gap']:.2f} ({-shape['gap_pct']:.0f}%) cheaper than a year out · {when}"
    return f"oil now and a year out cost about the same · {when}"


def curve_reading(shape: dict, before: dict | None) -> str:
    front, later = f"{shape['front_month']:%B %Y}", f"{shape['later_month']:%B %Y}"
    if shape["shape"] == "backwardation":
        text = (f"Oil for delivery in {front} costs **${shape['gap']:.2f} more** than oil for "
                f"{later} ({shape['gap_pct']:.0f}%). Buyers are paying extra to get oil "
                f"soon: the market is short of oil right now and expects that to ease.")
    elif shape["shape"] == "contango":
        text = (f"Oil for {later} costs **${-shape['gap']:.2f} more** than oil for {front} "
                f"({-shape['gap_pct']:.0f}%). There's more oil around than buyers need right "
                f"now, so traders are paid to store it for later.")
    else:
        text = (f"Oil for {front} and for {later} cost about the same: the market sees "
                f"supply and demand roughly in balance.")
    if before:
        change = shape["gap_pct"] - before["gap_pct"]
        if abs(change) >= 2:
            more = "tighter" if change > 0 else "looser"
            text += (f" Three months ago the gap was {before['gap_pct']:+.0f}%, so the "
                     f"market has become **{more}**.")
        else:
            text += f" That's about where it was three months ago ({before['gap_pct']:+.0f}%)."
    return text


def curve_section(brent_curve: pd.DataFrame, hour: str) -> None:
    st.markdown("**The futures curve: is oil scarce right now?**")
    market = st.segmented_control("Curve market", ["BRENT", "WTI"], default="BRENT",
                                  key="curve_market", label_visibility="collapsed",
                                  format_func=lambda k: {"BRENT": "Brent", "WTI": "WTI"}[k]) \
        or "BRENT"
    table = brent_curve if market == "BRENT" else _curve(market, hour)
    shape = sg.curve_shape(table)
    if shape is None:
        st.info("The futures curve isn't available right now. It comes from a free "
                "price feed that sometimes doesn't answer; try again later.")
        return
    st.markdown(curve_reading(shape, sg.curve_shape(table, "3 months ago")))

    dates = table.attrs.get("dates", {})
    fig = go.Figure()
    for column in ["3 months ago", "1 month ago", "now"]:
        if table[column].isna().all():
            continue
        name = ("Today" if column == "now"
                else f"{column.capitalize()} ({ui.day(dates[column], year=False)})")
        fig.add_trace(go.Scatter(
            x=table["month"], y=table[column], mode="lines+markers", name=name,
            line=dict(color=NAVY if column == "now" else PAST[column],
                      width=3 if column == "now" else 1.6),
            marker=dict(size=5 if column == "now" else 3),
            hovertemplate=f"{name} · delivery %{{x|%b %Y}}: $%{{y:.2f}}<extra></extra>"))
    ui.base_layout(fig, 360, hovermode="closest", yaxis_tickprefix="$",
                   xaxis_title="Delivery month", yaxis_title="Price per barrel")
    fig.update_xaxes(tickformat="%b %Y")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"curve_{market}")

    history = sg.load_snapshots()
    history = history[history["market"] == market]
    if len(history) >= 10:
        gap = (history["front"] / history["month_12"] - 1) * 100
        small = go.Figure(go.Scatter(x=history["date"], y=gap, mode="lines",
                                     line=dict(color=NAVY, width=1.6),
                                     hovertemplate="%{x|%b %-d, %Y}: %{y:+.1f}%<extra></extra>"))
        small.add_hline(y=0, line_color="#c3c2b7", line_width=1)
        ui.base_layout(small, 220, yaxis_ticksuffix="%",
                       yaxis_title="Front vs 12 months out")
        st.markdown("**The gap over time**")
        st.plotly_chart(small, width="stretch", config=ui.CHART_CONFIG, key=f"curve_hist_{market}")

    ui.tip("Each point is the price agreed today for oil delivered in that month (a futures "
           "contract). When near months cost more than later ones (the line slopes down) "
           "traders call it backwardation: oil is scarce now. When later months cost more "
           "(the line slopes up) it's contango: there's plenty of oil, and the higher later "
           "price pays for storing it. Grey lines show the same delivery months earlier, so "
           "you can see the curve steepen or flatten. Prices are futures traded on NYMEX.",
           "How to read this")


def bw_reading(s: dict) -> str:
    word = sg.level_word(s["pct_below"])
    text = (f"Brent costs **${s['now']:.2f} more** than WTI, {word} for the past decade "
            f"(typical ${s['low']:.0f}–{s['high']:.0f}; a year ago ${s['year_ago']:.2f}). ")
    if s["pct_below"] >= 70:
        text += ("World oil is dear next to U.S. oil: the market outside the U.S. is tighter, "
                 "which usually points to supply trouble abroad (the Middle East, sanctions) "
                 "or U.S. export routes running full.")
    elif s["pct_below"] <= 30:
        text += ("U.S. oil costs nearly as much as world oil: the U.S. market is relatively "
                 "tight, or U.S. oil is flowing freely to buyers abroad.")
    else:
        text += "World and U.S. oil are priced about as usual against each other."
    return text


def margin_reading(s: dict) -> str:
    word = sg.level_word(s["pct_below"])
    text = (f"Refiners earn about **${s['now']:.2f} a barrel** turning Brent into gasoline "
            f"and diesel, {word} for the past decade (typical ${s['low']:.0f}–"
            f"{s['high']:.0f}; a year ago ${s['year_ago']:.2f}). ")
    if s["pct_below"] >= 70:
        text += ("Fuel is expensive next to crude, so refiners want to run flat out and buy "
                 "more crude, which supports oil prices. High margins usually mean fuel "
                 "supplies are tight (refinery outages, low diesel stocks, strong demand).")
    elif s["pct_below"] <= 30:
        text += ("Fuel is cheap next to crude, so refiners may run less and buy less crude, "
                 "a weak sign for oil demand.")
    else:
        text += "Fuel and crude are priced about as usual against each other."
    return text


def gap_section(series: pd.Series, s: dict, key: str, title: str, color: str,
                reading: str, explain: str) -> None:
    st.markdown(f"**{title}**")
    st.markdown(reading)
    since = series[series.index >= sg.SINCE]
    fig = go.Figure()
    fig.add_hrect(y0=s["low"], y1=s["high"], fillcolor=ui.rgba(color, 0.08), line_width=0,
                  layer="below")
    fig.add_hline(y=s["median"], line_color=ui.rgba(color, 0.6), line_dash="dot",
                  line_width=1)
    fig.add_trace(go.Scatter(x=since.index, y=since.values, mode="lines",
                             line=dict(color=color, width=1.2), name=title,
                             hovertemplate="%{x|%b %-d, %Y}: $%{y:.2f}<extra></extra>"))
    ui.base_layout(fig, 340, showlegend=False, yaxis_tickprefix="$",
                   yaxis_title="$ per barrel")
    fig.update_layout(margin=dict(l=8, r=8, t=36, b=8))
    fig.update_xaxes(range=[since.index[-1] - pd.DateOffset(years=3),
                            since.index[-1] + pd.Timedelta(days=15)],
                     rangeselector=dict(buttons=[
                         dict(count=1, label="1 year", step="year", stepmode="backward"),
                         dict(count=3, label="3 years", step="year", stepmode="backward"),
                         dict(step="all", label="Since 2015")],
                         x=1, xanchor="right", y=1.02, yanchor="bottom", bgcolor="#ffffff",
                         activecolor="#dbe5f1", bordercolor="#e1e0d9", borderwidth=1,
                         font=dict(size=12)))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"gap_{key}")
    ui.tip(explain + f" The shaded band is the typical range (middle 80% of days since 2015); the "
           f"dotted line is the median, ${s['median']:.2f}.",
           "What this measures")
