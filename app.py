"""
Oil Tracker website.

Run it with:   streamlit run app.py
Then it opens in your browser at http://localhost:8501

This file loads the data and lays out the page. Each tab's content lives in
its own file: news_page.py, bot_dashboard.py, conditions.py, lab_page.py,
and the event pages below. Shared styling and chart pieces are in ui.py.
"""

import pandas as pd
import streamlit as st

import backtest as bt
import bot_dashboard
import conditions
import event_study as es
import fed_events as fed
import fetch_prices
import inventory_events as inv
import lab_page
import market_data as md
import news
import news_page
import strategies as strat
import ui

st.set_page_config(page_title="Oil Tracker", page_icon="🛢️", layout="wide")
ui.apply_styles()


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
    inv_events = inv.build_events(inv.load_inventories())
    timelines = news.load_timelines()   # refreshed daily by a GitHub Action
    return {
        "prices": prices,
        "opec": es.compute_results(prices, es.load_events()),
        "inventory": es.compute_results(prices, inv_events),
        "inv_events": inv_events,
        "fed": es.compute_results(prices, fed.build_events(fed.load_fed())),
        "timelines": timelines,
        "news": es.compute_results(prices, news.all_spikes(timelines)),
        "features": (features := strat.build_features(prices)),
        "backtests": bt.run_all(features),
    }


data = get_data()
prices = data["prices"]
news_results, news_paths = data["news"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
left, right = st.columns([5, 1], vertical_alignment="center")
left.markdown(
    '<p class="hero-title">🛢️ Oil Tracker</p>'
    '<p class="hero-sub">Today\'s oil news, matched to similar moments in the past, '
    'and what the market did next.</p>', unsafe_allow_html=True)
# A popover opens instantly in the browser (no page re-run).
about = right.popover("How this works", icon=":material/info:", width="stretch")

st.write("")
heat = news.current_heat(data["timelines"])
latest_date, latest_price = prices.index[-1], prices.iloc[-1]
n_events = sum(len(data[k][0]) for k in ("opec", "inventory", "fed", "news"))
k1, k2, k3, k4 = st.columns(4)
k1.metric("Brent crude", f"${latest_price:.2f}",
          f"{(latest_price / prices.iloc[-6] - 1) * 100:+.1f}% over 5 trading days",
          border=True)
if heat.empty:
    k2.metric("Biggest oil story now", "—", "news data loading", delta_color="off", border=True)
else:
    top = heat.iloc[0]
    note = (f"{top['heat']:.1f}× its normal news coverage" if top["heat"] >= 1.5
            else f"quiet news day: top topic at {top['heat']:.1f}× normal")
    k2.metric("Biggest oil story now", top["label"], note, delta_color="off", border=True)
k3.metric("Past events analysed", f"{n_events:,}",
          "news spikes, OPEC+, EIA and Fed", delta_color="off", border=True)
k4.metric("Price data through", f"{latest_date:%b %d, %Y}",
          f"history back to {prices.index[0].year}", delta_color="off", border=True)
st.write("")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_news, tab_bots, tab_cond, tab_lab, tab_events = st.tabs([
    ":material/newspaper: News → past",
    ":material/smart_toy: Paper trading bots",
    ":material/thermostat: Market conditions",
    ":material/science: Strategy lab",
    ":material/event: Scheduled events",
])

with tab_bots:
    bot_dashboard.render()

with tab_cond:
    conditions.render(data["features"])

with tab_lab:
    lab_page.render(data["features"], *data["backtests"], data["inv_events"])

# ---------------------------------------------------------------------------
# Scheduled events: EIA reports, OPEC+ meetings, Fed decisions
# ---------------------------------------------------------------------------
with tab_events:
    ui.eyebrow("Scheduled events")
    st.subheader("How oil reacted to regular, scheduled market news")
    kind = st.segmented_control(
        "Event type", ["EIA weekly inventories", "OPEC+ decisions", "Fed rate decisions"],
        default="EIA weekly inventories", key="event_kind") or "EIA weekly inventories"

    if kind == "EIA weekly inventories":
        inv_results, inv_paths = data["inventory"]
        latest = data["inv_events"].iloc[-1]
        similar = inv_results[inv_results["category"] == latest["category"]]
        st.markdown(f"""
Every Wednesday the EIA reports how much crude oil is stored in the U.S. A **draw**
(stocks falling) usually signals tight supply and tends to push prices **up**; a
**build** tends to push them **down**. Each week is compared with what's *normal for
that time of year* (5-year average), because stocks rise and fall with the seasons.

**Latest report ({latest['date']:%A %b %d, %Y}):** {latest['description']}, a surprise of
**{latest['surprise_mb']:+.1f}M barrels** → *{inv.LABELS[latest['category']]}*.
""")
        c1, c2, c3 = st.columns(3)
        c1.metric("Similar past reports", f"{len(similar)}", border=True)
        c2.metric("Brent on report day: average", f"{similar['day_1_pct'].mean():+.2f}%",
                  border=True)
        c3.metric("Brent rose on report day",
                  f"{(similar['day_1_pct'] > 0).mean():.0%} of the time", border=True)
        st.markdown("**Average reaction by size of surprise**")
        ui.comparison_section(prices, inv_results, inv_paths, "category", inv.CATEGORIES,
                              inv.LABELS, inv.COLORS, key="inv")
        st.markdown("**Explore the reports**")
        ui.drilldown_section(inv_results, inv_paths, "category", inv.CATEGORIES,
                             inv.LABELS, inv.COLORS, key="inv", select_label="Surprise size",
                             table_columns={
            "date": st.column_config.DateColumn("Report date", format="YYYY-MM-DD"),
            "change_mb": st.column_config.NumberColumn("Change (M bbl)", format="%+.1f"),
            "normal_mb": st.column_config.NumberColumn("Normal (M bbl)", format="%+.1f"),
            "surprise_mb": st.column_config.NumberColumn("Surprise (M bbl)", format="%+.1f"),
            **ui.HORIZON_COLUMNS,
        })

    elif kind == "OPEC+ decisions":
        opec_results, opec_paths = data["opec"]
        st.markdown("Major OPEC+ production decisions since 1999, from a hand-verified list.")
        st.markdown("**Average reaction by decision type**")
        ui.comparison_section(prices, opec_results, opec_paths, "decision", es.DECISIONS,
                              es.LABELS, es.COLORS, key="opec")
        st.markdown("**Explore individual decisions**")
        ui.drilldown_section(opec_results, opec_paths, "decision", es.DECISIONS,
                             es.LABELS, es.COLORS, key="opec", select_label="Decision type",
                             table_columns={
            "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "size_mbd": st.column_config.NumberColumn("Size (mb/d)", format="%.2f"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large"),
        })

    else:
        fed_results, fed_paths = data["fed"]
        st.markdown("""
Every change in the Federal Reserve's target interest rate since 1990. The **first move
of a new cycle** (a turn in policy) is separated from moves that **continue** a cycle.
The Fed usually cuts when the economy weakens and hikes when it's running hot, so these
results largely reflect the economy that prompted the decision.
""")
        st.markdown("**Average reaction by type of rate change**")
        ui.comparison_section(prices, fed_results, fed_paths, "decision", fed.CATEGORIES,
                              fed.LABELS, fed.COLORS, key="fed")
        st.markdown("**Explore individual rate changes**")
        ui.drilldown_section(fed_results, fed_paths, "decision", fed.CATEGORIES,
                             fed.LABELS, fed.COLORS, key="fed", select_label="Rate change type",
                             table_columns={
            "effective_date": st.column_config.DateColumn("Effective", format="YYYY-MM-DD"),
            "size_bp": st.column_config.NumberColumn("Change (bp)", format="%+d"),
            "new_rate": st.column_config.NumberColumn("New rate", format="%.2f%%"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large"),
        })
        st.caption("Measured from the close two business days before the change took effect, "
                   "so the reaction is never missed. Meetings where rates were held aren't included.")

# ---------------------------------------------------------------------------
# News tab - filled in LAST, although it's the first tab. The page is built
# top to bottom, so anything slow here (e.g. the live news feed) can never
# hold up the other tabs.
# ---------------------------------------------------------------------------
with tab_news:
    news_page.render(prices, data["timelines"], news_results, news_paths)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="footer">Data: GDELT Project (news), U.S. EIA, FRED / Federal Reserve, '
    'CFTC, Alpaca (live prices). A research tool, not investment advice.</div>',
    unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# "How this works" text, shown in the popover in the header
# ---------------------------------------------------------------------------
with about:
    st.markdown(f"""
### The idea
Find today's oil news, match it to similar moments in the past, and show what the
oil market did next.

### News
- **Source:** the GDELT Project, which monitors news worldwide. Searchable history
  starts in 2017.
- **Topics:** each topic (e.g. attacks on tankers) is a fixed news search. For every
  day we measure the topic's share of *all* news, so growth in GDELT's coverage
  doesn't distort comparisons.
- **News spike:** a day when a topic got at least {news.SPIKE_RATIO:.0f}× its normal share
  of coverage (normal = median of the previous {news.BASELINE_DAYS} days), with at least
  {news.MIN_ARTICLES} articles. Spikes must be {news.COOLDOWN_DAYS}+ days apart.
- **Timing:** we start from the close one business day *before* the spike, so the
  reaction isn't missed if the story broke the evening before.
- **Headlines** are tagged by keyword, so a few may land in the wrong topic.

### Other data
- **Prices:** daily Brent crude spot prices from the U.S. EIA, via FRED.
- **Inventories:** EIA weekly U.S. crude stocks, reports since 2006.
- **OPEC+ decisions:** a hand-verified list of major decisions since 1999.
- **Fed rate decisions:** the Fed's target rate via FRED; each change since 1990.
- **Positioning:** CFTC Commitments of Traders, "managed money" in NYMEX WTI.
- **Dollar:** Federal Reserve broad U.S. dollar index, via FRED.
- **Bots:** live prices and the paper account from Alpaca.

### Method
- **Starting point:** the closing price on the last trading day *before* each event.
- **Inventory surprise:** the week's change minus the average change for the same
  week over the previous 5 years (analyst forecasts aren't freely available).
- **Market conditions:** today's readings are compared with every day since 2007;
  "most similar days" compares all six indicators at once.
- **Backtests** only use data that was public at the time, charge {bt.COST_PCT:.2f}% per
  trade, and were designed on 2007–2016 and tested on 2017–now.

### Limits - please read
- **Markets react to surprises.** Expected news may barely move prices.
- **Small samples.** Some categories have only a handful of events; one extreme case
  (e.g. March 2020) can dominate an average.
- **Other news happens at the same time.** Moves aren't caused only by the event.
- Past reactions don't guarantee future ones. **Not investment advice.**
""")
