"""The homepage: every market the website covers, as a card with its live
price, a 3-month mini chart and a button into that market's own site."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import live_prices
import sites
import ui

ui.apply_styles()


@st.cache_data(ttl=5 * 60, show_spinner=False)
def _quote(market: str):
    return live_prices.quote(market)


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _closes(market: str) -> pd.Series:
    return live_prices.daily_closes(market, span="3mo")


now = pd.Timestamp.now(tz="America/New_York")
st.markdown(
    f'<div class="dateline">{now:%A}, {now:%B} {now.day}, {now:%Y}</div>'
    f'<div class="masthead">{ui.LOGO}<div><div class="wordmark">Market Tracker</div>'
    '<div class="dek">Commodity news set against similar moments in the past, and what the '
    'market did next. Pick a market to explore.</div></div></div>', unsafe_allow_html=True)
st.write("")


def sparkline(closes: pd.Series, color: str, key: str) -> None:
    if closes.empty:
        return
    up = closes.iloc[-1] >= closes.iloc[0]
    line = "#1d8a5e" if up else "#c43a39"
    fig = go.Figure(go.Scatter(x=closes.index, y=closes.values, mode="lines", line=dict(color=line, width=2),
                               fill="tozeroy", fillcolor=ui.rgba(line, 0.08),
                               hovertemplate="%{x|%b %-d}: $%{y:.2f}<extra></extra>"))
    low, high = closes.min(), closes.max()
    pad = (high - low) * 0.15 or 1
    fig.update_layout(height=110, margin=dict(l=0, r=0, t=4, b=0), showlegend=False,
                      xaxis=dict(visible=False), yaxis=dict(visible=False, range=[low - pad, high + pad]),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=key)


cols = st.columns(len(sites.SITES) + 1, gap="medium")
for col, site in zip(cols, sites.SITES):
    with col.container(border=True, key=f"market_{site['key']}"):
        st.markdown(f"<div class='market-name' style='color:{site['color']}'>{site['name']}</div>",
                    unsafe_allow_html=True)
        q = _quote(site["live"])
        closes = _closes(site["live"])
        if q:
            change = q["change_pct"] or 0
            arrow, tone = ("▲", "#1d8a5e") if change >= 0 else ("▼", "#c43a39")
            three = ((closes.iloc[-1] / closes.iloc[0] - 1) * 100) if len(closes) > 1 else None
            st.markdown(
                f"<div class='kpi-label'>{site['price_label']}</div>"
                f"<div class='market-price'>${q['price']:.2f} <span class='market-unit'>{site['unit']}</span></div>"
                f"<div class='kpi-note' style='color:{tone}'>{arrow} {change:+.1f}% today"
                + (f"<span style='color:#898781'> · {three:+.0f}% over 3 months</span>" if three is not None else "")
                + "</div>", unsafe_allow_html=True)
        else:
            st.caption("Live price unavailable right now.")
        sparkline(closes, site["color"], f"spark_{site['key']}")
        st.markdown(f"<div class='market-blurb'>{site['blurb']}</div>"
                    + "".join(f"<span class='market-chip'>{f}</span>" for f in site["features"]),
                    unsafe_allow_html=True)
        if st.button(f"Open the {site['name'].lower()} site →", key=f"open_{site['key']}", type="primary",
                     width="stretch"):
            st.switch_page(site["page"])

with cols[-1].container(border=True, key="market_soon"):
    st.markdown("<div class='market-name' style='color:#898781'>More markets</div>"
                "<div class='market-blurb'>Gold, wheat and copper are next on the list: each with its own "
                "news topics, scheduled reports and history of how prices reacted.</div>"
                "<span class='market-chip'>Coming soon</span>", unsafe_allow_html=True)

st.write("")
st.markdown(
    "<div class='footer'><b>Market Tracker</b> is an independent research project. Nothing here is investment "
    "advice, and past reactions are no guarantee of future ones. Live prices are futures, about 10 minutes "
    "delayed.</div>", unsafe_allow_html=True)
