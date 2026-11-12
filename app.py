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

import pandas as pd
import streamlit as st

import backtest as bt
import bot
import bot_dashboard
import conditions
import event_study as es
import fed_events as fed
import fetch_prices
import flash_sources
import history_page
import alerts
import live_prices
import methodology
import glossary
import signals
import signals_page
import inventory_events as inv
import lab_page
import market_data as md
import market_news as mn
import mediacloud_news
import news_feeds
import upcoming
import recap
import markets as mk
import news
import daily_move
import storylines
import storylines_page
import news_page
import strategies as strat
import ui

st.set_page_config(page_title="Oil Tracker · oil news and market history",
                   page_icon=":material/water_drop:", layout="wide")


# ---------------------------------------------------------------------------
# Keep our own files in step after an update. Streamlit Cloud re-reads this
# file on every visit but can keep OLD copies of the other files it already
# loaded, so new app.py + old ui.py = crash. Reload them (dependencies first)
# whenever any of them changed on disk, and once when the server starts.
# ---------------------------------------------------------------------------
OWN_MODULES = [es, inv, md, fed, fetch_prices, strat, bt, bot, mediacloud_news, news, news_feeds, flash_sources, mn, upcoming, recap, mk, ui, daily_move, live_prices,
               storylines, conditions, lab_page, bot_dashboard, storylines_page, news_page, history_page,
               methodology, glossary, signals, signals_page, alerts]


@st.cache_resource
def _loaded_versions() -> dict:
    return {}          # one per server process: {module name: file timestamp}


def _reload_if_changed() -> bool:
    """Reload our modules if any file changed; True if it did."""
    seen = _loaded_versions()
    current = {m.__name__: os.path.getmtime(m.__file__) for m in OWN_MODULES}
    if seen == current:
        return False
    for module in OWN_MODULES:
        importlib.reload(module)
    seen.clear()
    seen.update(current)
    return True


# New code can expect data the old code never built (e.g. a new column), so
# after an update the saved data is rebuilt too (see get_data below).
CODE_CHANGED = _reload_if_changed()
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


@st.cache_resource(ttl=6 * 60 * 60, show_spinner="Loading prices and news history (this takes a few seconds after a quiet spell)...")
def get_data():
    # The four downloads don't depend on each other, so run them at once
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_download, (fetch_prices.main, inv.download_inventories,
                                  md.main, fed.download_fed)))
    prices = es.load_prices()                 # Brent: the site's main market
    markets = mk.load_markets()               # Brent, WTI, gasoline, ... (markets.py)
    inv_events = inv.build_events(inv.load_inventories())
    timelines = news.load_worldwide()   # Media Cloud, refreshed every 3 hours by a GitHub Action
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


# ---------------------------------------------------------------------------
# Header - drawn BEFORE the data loads, so a visitor sees the site straight
# away (with a short loading line under it) instead of a blank page.
# ---------------------------------------------------------------------------
left, right = st.columns([5, 1], vertical_alignment="center")
left.markdown(ui.masthead(pd.Timestamp.now(tz="America/New_York")), unsafe_allow_html=True)
actions = right.container(key="top_actions")      # (side by side and small on phones)
if actions.button("Methodology", width="stretch", key="method_top"):
    methodology.show()
if actions.button("Oil 101", width="stretch", key="glossary_top",
                  help="The words the oil market uses, in plain English."):
    glossary.show()
actions.link_button("Spike alerts", alerts.SUBSCRIBE_URL, width="stretch",
                    help="Free push notifications (ntfy app or browser) when an oil news topic "
                         "starts spiking, with what happened after past spikes.")

if CODE_CHANGED:
    get_data.clear()
data = get_data()
prices = data["prices"]

st.write("")
@st.cache_data(ttl=5 * 60, show_spinner=False)
def live_quote(market: str) -> dict | None:
    return live_prices.quote(market)       # shared by all visitors, refreshed every 5 min


def price_card(label: str, market: str) -> tuple:
    """Live futures price if we can get it, else the latest daily spot price (dated)."""
    q = live_quote(market)
    if q is not None:
        change = q["change_pct"]
        arrow, color = ("▲", "#1d8a5e") if (change or 0) >= 0 else ("▼", "#c43a39")
        t = q["time"]
        clock = f"{t.hour % 12 or 12}:{t:%M} {'pm' if t.hour >= 12 else 'am'} ET"
        today = pd.Timestamp.now(tz=t.tz).date() == t.date()
        when = clock if today else f"{t:%b} {t.day}, {clock}"
        note = (f"{arrow} {change:+.1f}% · {when}" if change is not None else when)
        return (label, f"${q['price']:.2f}", note, color)
    series = data["markets"][market]
    return (label, f"${series.iloc[-1]:.2f}",
            f"daily spot price, {ui.day(series.index[-1], year=False)} (live price unavailable)", None)


@st.fragment(run_every=5 * 60)        # the price cards keep themselves up to date
def header_cards() -> None:
    heat, _ = news_page.current_heat(data)
    n_events = sum(len(data[k][0]) for k in ("opec", "inventory", "fed", "news"))
    busy = heat[heat["enough"]] if not heat.empty else heat
    if heat.empty:
        story = ("Biggest oil story now", "—", "news data loading", None)
    elif busy.empty:
        story = ("Biggest oil story now", "No topic stands out", "a quiet news day", None)
    else:
        top = busy.iloc[0]
        note = (f"{top['heat']:.1f}× its normal news coverage" if top["heat"] >= 1.5
                else f"quiet news day: top topic at {top['heat']:.1f}× normal")
        if top["heat"] >= 1.5 and top["one_day"]:
            note += f", mostly on {ui.day(top['peak_day'], year=False)}"
        story = ("Biggest oil story now", top["label"], note, None)
    ui.kpi_row([
        price_card("Brent crude", "BRENT"),
        price_card("WTI crude", "WTI"),
        story,
        ("Past events analysed", f"{n_events:,}", "news spikes, OPEC+, EIA and Fed", None),
    ])
    st.caption(f"Prices: front-month futures, about 10 min delayed. Charts and research use "
               f"official daily spot prices, published about a week late (latest "
               f"{ui.day(prices.index[-1], year=False)}).")


header_cards()
st.write("")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_news, tab_signals, tab_history, tab_bots, tab_cond, tab_lab, tab_events = st.tabs([
    "News",
    "Market signals",
    "Event history",
    "Trading bots",
    "Market conditions",
    "Strategy lab",
    "Scheduled events",
])

with tab_signals:
    safe(signals_page.render, data)

with tab_history:
    safe(history_page.render, data)

with tab_bots:
    safe(bot_dashboard.render)

@st.cache_data(ttl=30 * 60, show_spinner=False)
def current_features(version: str):
    """Today's readings for Market conditions and the Strategy lab: the official
    price history (about a week behind) carried up to today with futures
    prices. Research and backtests keep using the official prices only."""
    extended, added = live_prices.extend(prices)
    if not added:
        return data["features"], 0
    return strat.build_features(extended), added


now_features, recent_days = current_features(f"{prices.index[-1]}-{len(prices)}")

with tab_cond:
    safe(conditions.render, now_features, recent_days)

with tab_lab:
    safe(lab_page.render, data["features"], *data["backtests"], data["inv_events"],
         now_features, recent_days)

# ---------------------------------------------------------------------------
# Scheduled events: EIA reports, OPEC+ meetings, Fed decisions.
# A fragment: switching between them only redraws this tab, not the site.
# ---------------------------------------------------------------------------
EVENT_KINDS = {
    "EIA weekly inventories": dict(
        set="inventory", cat_col="category", categories=inv.CATEGORIES, labels=inv.LABELS,
        colors=inv.COLORS, heading="size of surprise", select_label="Surprise size",
        explore="Explore the reports", table_columns={
            "date": st.column_config.DateColumn("Report date", format="MMM D, YYYY"),
            "change_mb": st.column_config.NumberColumn("Change (M bbl)", format="%+.1f"),
            "normal_mb": st.column_config.NumberColumn("Normal (M bbl)", format="%+.1f"),
            "surprise_mb": st.column_config.NumberColumn("Surprise (M bbl)", format="%+.1f"),
            **ui.HORIZON_COLUMNS}),
    "OPEC+ decisions": dict(
        set="opec", cat_col="decision", categories=es.DECISIONS, labels=es.LABELS,
        colors=es.COLORS, heading="decision type", select_label="Decision type",
        explore="Explore individual decisions", table_columns={
            "date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
            "size_mbd": st.column_config.NumberColumn("Size (mb/d)", format="%.2f"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large")}),
    "Fed rate decisions": dict(
        set="fed", cat_col="decision", categories=fed.CATEGORIES, labels=fed.LABELS,
        colors=fed.COLORS, heading="type of rate change", select_label="Rate change type",
        explore="Explore individual rate changes", table_columns={
            "effective_date": st.column_config.DateColumn("Effective", format="MMM D, YYYY"),
            "size_bp": st.column_config.NumberColumn("Change (bp)", format="%+d"),
            "new_rate": st.column_config.NumberColumn("New rate", format="%.2f%%"),
            **ui.HORIZON_COLUMNS,
            "description": st.column_config.TextColumn("What happened", width="large")}),
}


@st.fragment
def scheduled_events() -> None:
    st.subheader("Reports, meetings and rate decisions", anchor=False)
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

**Latest report ({ui.day(latest['date'], weekday=True)}):** {latest['description']}, a surprise of
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
    '<div class="footer"><div><b>Oil Tracker</b> is an independent research project. '
    'Nothing here is investment advice, and past reactions are no guarantee of future ones.</div>'
    '<div>Data: news articles from about 30 publishers’ news feeds · Media Cloud (worldwide news coverage) · Benzinga via Alpaca (newswire) · '
    'U.S. EIA · FRED / Federal Reserve · CFTC · Yahoo Finance (live futures prices)</div></div>',
    unsafe_allow_html=True)
if st.button("How the numbers are worked out →", type="tertiary", key="method_footer"):
    methodology.show()

