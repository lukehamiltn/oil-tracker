"""
Oil Tracker website.

Run it with:   streamlit run app.py
Then it opens in your browser at http://localhost:8501

This file loads the data and lays out the page. Each tab's content lives in
its own file: news_page.py, bot_dashboard.py, conditions.py, lab_page.py,
and the event pages below. Shared styling and chart pieces are in ui.py.
"""

import importlib
import os
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

import backtest as bt
import bot
import bot_dashboard
import conditions
import event_study as es
import fed_events as fed
import fetch_prices
import history_page
import inventory_events as inv
import lab_page
import market_data as md
import market_news as mn
import markets as mk
import news
import news_page
import strategies as strat
import ui

st.set_page_config(page_title="Oil Tracker", page_icon="🛢️", layout="wide")


# ---------------------------------------------------------------------------
# Keep our own files in step after an update. Streamlit Cloud re-reads this
# file on every visit but can keep OLD copies of the other files it already
# loaded, so new app.py + old ui.py = crash. Reload them (dependencies first)
# whenever any of them changed on disk, and once when the server starts.
# ---------------------------------------------------------------------------
OWN_MODULES = [es, inv, md, fed, fetch_prices, strat, bt, bot, news, mn, mk, ui,
               conditions, lab_page, bot_dashboard, news_page, history_page]


@st.cache_resource
def _loaded_versions() -> dict:
    return {}          # one per server process: {module name: file timestamp}


def _reload_if_changed() -> None:
    seen = _loaded_versions()
    current = {m.__name__: os.path.getmtime(m.__file__) for m in OWN_MODULES}
    if seen != current:
        for module in OWN_MODULES:
            importlib.reload(module)
        seen.clear()
        seen.update(current)


_reload_if_changed()
ui.apply_styles()


def safe(render, *args) -> None:
    """Draw one tab; if it ever fails, say so in that tab only, so the other
    tabs still load (the details go to the server log)."""
    try:
        render(*args)
    except Exception as error:
        print(f"Tab failed: {render.__name__}: {error!r}")
        st.error("This section hit a problem and couldn't load. The rest of the site "
                 "works; please try refreshing in a minute.")


# ---------------------------------------------------------------------------
# Data - cached so the site doesn't redo the work on every click.
# ttl = refresh at most every 6 hours (downloads fresh data each time).
# cache_resource shares ONE copy between all visitors and clicks instead of
# copying it every time (the pages only read this data, never change it).
# ---------------------------------------------------------------------------
def _download(job) -> None:
    # If a source is temporarily down, carry on with the copy we already
    # have (if any) rather than crashing the site.
    try:
        job()
    except Exception as error:
        print(f"Download failed, using saved data instead: {error}")


@st.cache_resource(ttl=6 * 60 * 60, show_spinner="Loading the latest oil data...")
def get_data():
    # The four downloads don't depend on each other, so run them at once
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_download, (fetch_prices.main, inv.download_inventories,
                                  md.main, fed.download_fed)))
    prices = es.load_prices()                 # Brent: the site's main market
    markets = mk.load_markets()               # Brent, WTI, gasoline, ... (markets.py)
    inv_events = inv.build_events(inv.load_inventories())
    timelines = news.load_timelines()   # refreshed daily by a GitHub Action
    archive = mn.load_archive()         # refreshed every 3 hours by a GitHub Action
    market_timelines = mn.topic_timelines(archive)
    gdelt_spikes = mn.add_headlines(news.all_spikes(timelines), archive, mn.topic_match)
    market_spikes = mn.add_headlines(news.all_spikes(market_timelines, "market"),
                                     archive, mn.topic_match)
    # Each set of events measured in every market: react[set][market] = (results, paths)
    events = {"opec": es.load_events(), "inventory": inv_events,
              "fed": fed.build_events(fed.load_fed()), "news": gdelt_spikes,
              "market_news": market_spikes}
    react = {name: mk.reactions(markets, ev) for name, ev in events.items()}
    return {
        "prices": prices,
        "markets": markets,
        "typical": mk.typical_moves(markets),
        "sig": mk.Significance(markets),      # "is this real?" checks
        "react": react,
        "events": events,                     # every event, incl. ones too recent to measure
        # Brent results, used throughout the site
        **{name: react[name]["BRENT"] for name in react},
        "inv_events": inv_events,
        "timelines": timelines,
        "archive": archive,
        "market_timelines": market_timelines,
        "features": (features := strat.build_features(prices)),
        "backtests": bt.run_all(features),
    }


data = get_data()
prices = data["prices"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
left, right = st.columns([5, 1], vertical_alignment="center")
left.markdown(
    '<p class="hero-title">🛢️ Oil Tracker</p>'
    '<p class="hero-sub">Today\'s oil news, matched to similar moments in the past, '
    'and what the market did next.</p>', unsafe_allow_html=True)
# A popover opens instantly in the browser (no page re-run).
about = right.popover("ℹ️ How this works", width="stretch")

st.write("")
heat, _ = news_page.current_heat(data)
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
tab_news, tab_history, tab_bots, tab_cond, tab_lab, tab_events = st.tabs([
    ":material/newspaper: News → past",
    ":material/timeline: Event history",
    ":material/smart_toy: Paper trading bots",
    ":material/thermostat: Market conditions",
    ":material/science: Strategy lab",
    ":material/event: Scheduled events",
])

with tab_history:
    safe(history_page.render, data)

with tab_bots:
    safe(bot_dashboard.render)

with tab_cond:
    safe(conditions.render, data["features"])

with tab_lab:
    safe(lab_page.render, data["features"], *data["backtests"], data["inv_events"])

# ---------------------------------------------------------------------------
# Scheduled events: EIA reports, OPEC+ meetings, Fed decisions.
# A fragment: switching between them only redraws this tab, not the site.
# ---------------------------------------------------------------------------
EVENT_KINDS = {
    "EIA weekly inventories": dict(
        set="inventory", cat_col="category", categories=inv.CATEGORIES, labels=inv.LABELS,
        colors=inv.COLORS, heading="size of surprise", select_label="Surprise size",
        explore="Explore the reports", table_columns={
            "date": st.column_config.DateColumn("Report date", format="YYYY-MM-DD"),
            "change_mb": st.column_config.NumberColumn("Change (M bbl)", format="%+.1f"),
            "normal_mb": st.column_config.NumberColumn("Normal (M bbl)", format="%+.1f"),
            "surprise_mb": st.column_config.NumberColumn("Surprise (M bbl)", format="%+.1f"),
            **ui.HORIZON_COLUMNS}),
    "OPEC+ decisions": dict(
        set="opec", cat_col="decision", categories=es.DECISIONS, labels=es.LABELS,
        colors=es.COLORS, heading="decision type", select_label="Decision type",
        explore="Explore individual decisions", table_columns={
            "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "size_mbd": st.column_config.NumberColumn("Size (mb/d)", format="%.2f"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large")}),
    "Fed rate decisions": dict(
        set="fed", cat_col="decision", categories=fed.CATEGORIES, labels=fed.LABELS,
        colors=fed.COLORS, heading="type of rate change", select_label="Rate change type",
        explore="Explore individual rate changes", table_columns={
            "effective_date": st.column_config.DateColumn("Effective", format="YYYY-MM-DD"),
            "size_bp": st.column_config.NumberColumn("Change (bp)", format="%+d"),
            "new_rate": st.column_config.NumberColumn("New rate", format="%.2f%%"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large")}),
}


@st.fragment
def scheduled_events() -> None:
    ui.eyebrow("Scheduled events")
    st.subheader("How markets reacted to regular, scheduled news", anchor=False)
    kind = st.segmented_control("Event type", list(EVENT_KINDS),
                                default="EIA weekly inventories",
                                key="event_kind") or "EIA weekly inventories"
    k = EVENT_KINDS[kind]

    if kind == "EIA weekly inventories":
        latest = data["inv_events"].iloc[-1]
        st.markdown(f"""
Every Wednesday the EIA reports how much crude oil is stored in the U.S. A **draw**
(stocks falling) usually signals tight supply and tends to push prices **up**; a
**build** tends to push them **down**. Each week is compared with what's *normal for
that time of year* (5-year average), because stocks rise and fall with the seasons.

**Latest report ({latest['date']:%A %b %d, %Y}):** {latest['description']}, a surprise of
**{latest['surprise_mb']:+.1f}M barrels** → *{inv.LABELS[latest['category']]}*.
""")
    elif kind == "OPEC+ decisions":
        st.markdown("Major OPEC+ production decisions since 1999, from a hand-verified list.")
    else:
        st.markdown("""
Every change in the Federal Reserve's target interest rate since 1990. The **first move
of a new cycle** (a turn in policy) is separated from moves that **continue** a cycle.
The Fed usually cuts when the economy weakens and hikes when it's running hot, so these
results largely reflect the economy that prompted the decision.
""")

    market = ui.market_picker("events_market", data["markets"])
    name = mk.MARKETS[market][1]
    results, paths = data["react"][k["set"]][market]

    if kind == "EIA weekly inventories" and not results.empty:
        similar = results[results["category"] == latest["category"]]
        c1, c2, c3 = st.columns(3)
        c1.metric("Similar past reports", f"{len(similar)}", border=True)
        verdict = mk.VERDICTS[data["sig"].check(market, 1, similar["day_1_pct"])][0]
        c2.metric(f"{name} on report day: average", f"{similar['day_1_pct'].mean():+.2f}%",
                  verdict, delta_color="off", delta_arrow="off", border=True)
        c3.metric(f"{name} rose on report day",
                  f"{(similar['day_1_pct'] > 0).mean():.0%} of the time", border=True)

    st.markdown(f"**Average reaction in {mk.MARKETS[market][0]}, by {k['heading']}**")
    ui.comparison_section(data["markets"][market], results, paths, k["cat_col"],
                          k["categories"], k["labels"], k["colors"], key=k["set"], market=name,
                          sig=data["sig"], market_key=market)
    st.markdown("**The same events in every market**")
    ui.cross_market_section(data["react"][k["set"]], data["typical"], k["cat_col"],
                            k["categories"], k["labels"], key=k["set"], sig=data["sig"])
    st.markdown(f"**{k['explore']}** (in {mk.MARKETS[market][0]})")
    ui.drilldown_section(results, paths, k["cat_col"], k["categories"], k["labels"],
                         k["colors"], key=k["set"], select_label=k["select_label"],
                         table_columns=k["table_columns"], market=name)
    if kind == "Fed rate decisions":
        st.caption("Measured from the close two business days before the change took effect, "
                   "so the reaction is never missed. Meetings where rates were held aren't included.")


with tab_events:
    safe(scheduled_events)

# ---------------------------------------------------------------------------
# News tab - filled in LAST, although it's the first tab. The page is built
# top to bottom, so anything slow here (e.g. the live news feed) can never
# hold up the other tabs.
# ---------------------------------------------------------------------------
with tab_news:
    safe(news_page.render, prices, data)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="footer">Data: GDELT Project (worldwide news), Benzinga via Alpaca (market news), U.S. EIA, FRED / Federal Reserve, '
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
- **Two sources.** *Worldwide news* from the GDELT Project, which monitors news
  everywhere (history since 2017), and *market news* from Benzinga via Alpaca:
  financial news about oil funds and oil companies (history since 2015). The latest
  headlines and the search box use the market news archive, which is saved with the
  site, so searches are instant.
- **Topics:** each topic (e.g. attacks on tankers) is a fixed news search. For every
  day we measure the topic's share of *all* news, so growth in GDELT's coverage
  doesn't distort comparisons.
- **News spike:** a day when a topic got at least {news.SPIKE_RATIO:.0f}× its normal share
  of coverage (normal = median of the previous {news.BASELINE_DAYS} days), with at least
  {news.MIN_ARTICLES} articles, and among the topic's busiest 10% of days over the
  previous year. Spikes must be {news.COOLDOWN_DAYS}+ days apart. Hurricane spikes only
  count in hurricane season (June–November). Days when GDELT itself collected
  unusually few articles are skipped.
- **Timing:** we start from the close one business day *before* the spike, so the
  reaction isn't missed if the story broke the evening before.
- **Headlines** are tagged by keyword, so a few may land in the wrong topic. Each past
  spike shows the main market-news headline from that day, when there was one.
- **Like this before:** each story is turned into a list of word weights (TF-IDF),
  where rare words such as place and company names count most, and compared with
  every past oil story. Matches must be at least a week apart and from at least two
  weeks before the story, so the same event isn't counted twice.
- **Market news spikes** use the same rules with a lower article minimum, because that
  feed has a few dozen oil stories a day rather than thousands.

### Other data
- **Prices:** daily spot prices from the U.S. EIA via FRED for Brent and WTI crude,
  NY Harbor gasoline and heating oil, and Henry Hub natural gas; the Fed's broad
  dollar index (FRED); and the XLE energy-stock fund (Alpaca, dividends included).
- **Inventories:** EIA weekly U.S. crude stocks, reports since 2006.
- **OPEC+ decisions:** a hand-verified list of major decisions since 1999.
- **Fed rate decisions:** the Fed's target rate via FRED; each change since 1990.
- **Positioning:** CFTC Commitments of Traders, "managed money" in NYMEX WTI.
- **Dollar:** Federal Reserve broad U.S. dollar index, via FRED.
- **Bots:** live prices and the paper account from Alpaca.

### Method
- **Starting point:** the closing price on the last trading day *before* each event.
- **Several markets:** every event is measured the same way in each market. Markets
  move by very different amounts (natural gas swings far more than the dollar), so
  each is compared with its own typical move. Windows containing a zero or negative
  price (WTI in April 2020) are left out of that market.
- **Inventory surprise:** the week's change minus the average change for the same
  week over the previous 5 years (analyst forecasts aren't freely available).
- **Market conditions:** today's readings are compared with every day since 2007;
  "most similar days" compares all six indicators at once.
- **Backtests** only use data that was public at the time, charge {bt.COST_PCT:.2f}% per
  trade, and were designed on 2007–2016 and tested on 2017–now.

### Is this pattern real?
Every average is checked against luck. If an event type has 20 past cases, we pick
20 *random* days from the same market's history, thousands of times over, and see how
often their average move is as far from normal as the events' average was.
- **Strong pattern (●●):** random days do that less than 2% of the time.
- **Possible pattern (●):** less than 10% of the time.
- **Could be noise:** random days do it often, so the average may just be luck.
- **Too few events:** fewer than {mk.MIN_EVENTS} cases; we don't judge.

The site checks hundreds of averages, so a few "strong" labels will still be flukes
(about 1 in 50 of the checks that are really noise). Treat a pattern as more
convincing when it shows up across related markets (e.g. crude *and* gasoline).

### Limits - please read
- **Markets react to surprises.** Expected news may barely move prices.
- **Small samples.** Some categories have only a handful of events; one extreme case
  (e.g. March 2020) can dominate an average.
- **Other news happens at the same time.** Moves aren't caused only by the event.
- Past reactions don't guarantee future ones. **Not investment advice.**
""")
