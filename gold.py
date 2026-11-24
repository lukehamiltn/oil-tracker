"""
The gold site (the /gold page).

  header   live gold price, the next Fed decision, the real interest rate, and
           the gold story getting the most extra coverage
  News     Today: why gold moved, gold news topics (click one for its stories)
           with what gold did after past spikes, and the latest gold
           headlines. Also: Topics over time and Search (commodity_news.py)
  Week in review  how gold moved each week, the real interest rate, what made
           the news, and what history suggested vs what happened
  Fed & interest rates  gold against the real interest rate, and how gold
           reacted to every Fed rate change since 2004
  Prices & history  gold since 2005 with news spikes marked, and how gold
           usually moves in each month
  Market conditions  today's readings (trend, volatility, real rates, the
           dollar) against history, and the past days most like today

Gold's price history comes from GLD, the biggest gold fund (fetch_prices.py),
from late 2004. The machinery is shared with the oil and gas sites: news.py
(topics and spikes), event_study.py (price reactions), markets.py (is a
pattern real?), ui.py.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import alerts
import commodity_news as cn
import conditions
import event_study as es
import fed_events as fed
import fetch_prices
import gas_storage as gs
import glossary
import gold_review
import live_prices
import market_news as mn
import mediacloud_news
import news
import ui

ui.apply_styles()

MARKET = "GOLD"
SPEC = cn.GOLD          # the shared News tab, set up for gold
COLOR = SPEC.color


# Data ---------------------------------------------------------------------------
@st.cache_resource(ttl=6 * 60 * 60, show_spinner="Loading gold prices and history...")
def gold_data() -> dict:
    # Prices: download if the saved copy is missing or more than a few days old
    try:
        prices = es.load_prices(MARKET)
        stale = prices.empty or (pd.Timestamp.now() - prices.index[-1]).days > 4
    except Exception:
        stale = True
    if stale:
        try:
            fetch_prices.main()
        except Exception as error:
            print(f"Price download failed, using saved data: {error}")
    try:
        fed.download_fed()
    except Exception as error:
        print(f"Fed download failed, using saved data: {error}")
    data = gold_review.build(es.load_prices(MARKET), es.load_prices("REAL_YIELD"),
                             mediacloud_news.load(mediacloud_news.GOLD_PATH))
    data["dollar"] = es.load_prices("DOLLAR")
    return data


# (Every page runs under the same name, so Streamlit's cache can't tell two
# functions with identical code apart: gas.py's live_quote() would answer for
# gold. Hence gold_... names, with the market passed in.)
@st.cache_data(ttl=5 * 60, show_spinner=False)
def gold_quote(market: str = MARKET):
    return live_prices.quote(market)


@st.cache_data(ttl=30 * 60, show_spinner=False)
def gold_closes(hour: str, market: str = MARKET) -> pd.Series:
    return live_prices.daily_closes(market, span="6mo")


@st.cache_data(ttl=30 * 60, show_spinner=False)
def gold_conditions(version: str) -> tuple[pd.DataFrame, pd.Series, int]:
    """Market conditions for every day up to today: the GLD-based prices
    carried up to today with futures."""
    extended, added = live_prices.extend(prices, MARKET)
    return conditions.gold_table(extended, data["real_yield"], data["dollar"]), extended, added


@st.cache_data(ttl=3 * 60 * 60, show_spinner=False)
def gold_archive() -> pd.DataFrame:
    """Gold stories from the market newswire (collected since mid-2026)."""
    return mn.load_gold_archive()


def gold_headlines() -> pd.DataFrame:
    return cn.live_headlines(SPEC.key, gold_archive())


data = gold_data()
prices = data["prices"]
heat = news.current_heat(data["timelines"]) if not data["timelines"].empty else pd.DataFrame()


def upcoming_fed() -> list[pd.Timestamp]:
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    try:
        dates = pd.read_csv("events/upcoming.csv", parse_dates=["date"]).query("kind == 'fed'")["date"]
        return sorted(d for d in dates if d >= today)
    except Exception:
        return []


# Header -------------------------------------------------------------------------
ui.back_link()
now = pd.Timestamp.now(tz="America/New_York")
left, right = st.columns([2, 1], vertical_alignment="top")
left.markdown(
    f'<div class="dateline">{now:%A}, {now:%B} {now.day}, {now:%Y}</div>'
    f'<div class="masthead">{ui.LOGO}<div><div class="wordmark">Gold Tracker</div>'
    '<div class="dek">The news that moves gold, set against similar moments in the past '
    'and what the price did next.</div></div></div>', unsafe_allow_html=True)
actions = right.container(key="top_actions")
if actions.button("Terminology", key="gold_glossary", help="The words the gold market uses, in plain English."):
    glossary.show_gold()
actions.link_button("Spike alerts", alerts.GOLD_SUBSCRIBE_URL, width="stretch",
                    help="Free push notifications (ntfy app or browser) when a gold news topic starts "
                         "spiking, with what happened after past spikes, plus a Saturday week in review.")
st.write("")

q = gold_quote()
if q:
    change = q["change_pct"] or 0
    t = q["time"]
    clock = f"{t.hour % 12 or 12}:{t:%M} {'pm' if t.hour >= 12 else 'am'} ET"
    price_card = ("Gold", f"${q['price']:,.0f}", f"{'▲' if change >= 0 else '▼'} {change:+.1f}% · {clock}",
                  "#1d8a5e" if change >= 0 else "#c43a39")
else:
    price_card = ("Gold", f"${prices.iloc[-1]:,.0f}", f"per ounce, {ui.day(prices.index[-1], year=False)}", None)
fed_dates = upcoming_fed()
real = data["real_yield"]
month_ago = real[real.index <= real.index[-1] - pd.Timedelta(days=30)]
real_change = real.iloc[-1] - month_ago.iloc[-1] if len(month_ago) else 0
busy = heat[heat["enough"]] if not heat.empty else heat
story = (("Biggest gold story", busy.iloc[0]["label"], f"{busy.iloc[0]['heat']:.1f}× its normal news coverage", None)
         if len(busy) else ("Biggest gold story", "Quiet", "no topic stands out", None))
ui.kpi_row([
    price_card,
    ("Next Fed decision", ui.day(fed_dates[0], year=False, weekday=True) if fed_dates else "—",
     "2:00pm ET" if fed_dates else "no date published yet", None),
    ("10-year real interest rate", f"{real.iloc[-1]:.2f}%",
     f"{real_change:+.2f} points in a month · {ui.day(real.index[-1], year=False)}",
     "#c43a39" if real_change > 0.05 else "#1d8a5e" if real_change < -0.05 else None),
    story,
])
st.caption(f"Live price: COMEX gold futures, about 10 minutes delayed. Charts use daily closing prices "
           f"(latest {ui.day(prices.index[-1], year=False)}), worked out from the GLD gold fund.")
st.write("")

tab_news, tab_review, tab_fed, tab_history, tab_cond = st.tabs(
    ["News", "Week in review", "Fed & interest rates", "Prices & history", "Market conditions"])


# News ---------------------------------------------------------------------------------
def headline_rows(heads: pd.DataFrame) -> None:
    cn.headline_rows(SPEC, heads)


def coming_up() -> None:
    if not fed_dates:
        return
    st.subheader("Coming up", anchor=False)
    today = now.tz_localize(None).normalize()
    cards = []
    for day in fed_dates[:3]:
        days = (day.normalize() - today).days
        when = "Today" if days == 0 else "Tomorrow" if days == 1 else f"In {days} days"
        cards.append((f"{when} · {day:%a %b} {day.day}", "Fed rate decision", "2:00pm ET", None))
    ui.kpi_row(cards, columns=len(cards))
    ui.tip("The Fed's rate decisions are the scheduled events that move gold most: see the Fed & interest "
           "rates tab for how gold reacted to past ones. Dates from the Fed's published calendar.",
           "About this calendar")


def headlines() -> None:
    st.subheader("Latest gold headlines", anchor=False)
    heads = gold_headlines()
    if heads.empty:
        st.info("No gold headlines in the last day or two.")
        return
    headline_rows(heads.head(12))
    ui.tip("Articles from our publishers' news feeds and the market newswire that mention gold or bullion, "
           "newest first.", "About these stories")


with tab_news:
    try:
        view = cn.pick_view(SPEC)
        if view == "topics":
            cn.topics_view(SPEC, prices, data, gold_archive())
        elif view == "search":
            cn.search_view(SPEC, prices, data["sig"], gold_archive())
        else:
            cn.why_today(SPEC, q, prices, gold_headlines(), heat, headline_rows)
            st.write("")
            cn.topic_cards(SPEC, data, heat, lambda topic, row: cn.topic_dialog(
                SPEC, topic, row, gold_headlines(), gold_archive(), headline_rows))
            st.write("")
            coming_up()
            st.write("")
            headlines()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")


# Fed & interest rates --------------------------------------------------------------
def real_rate_section() -> None:
    st.subheader("Gold and the real interest rate", anchor=False)
    st.markdown("Gold pays no interest. When the **real** interest rate (what a safe Treasury bond pays "
                "after inflation) is high, holding gold means giving up a lot; when it's low or negative, "
                "you give up little. So for years gold moved like a mirror image of real rates.")
    both = pd.DataFrame({"gold": prices, "real": real}).dropna()
    weekly = both.resample("W-FRI").last().dropna()
    changes = pd.DataFrame({"gold": weekly["gold"].pct_change(13) * 100,
                            "real": weekly["real"].diff(13)}).dropna()
    before = changes[changes.index < "2022-01-01"].corr().loc["gold", "real"]
    since = changes[changes.index >= "2022-01-01"].corr().loc["gold", "real"]
    start = both[both.index < "2022-01-01"].iloc[-1]          # the end of 2021
    rate_rise = both["real"].iloc[-1] - start["real"]
    gold_move = (both["gold"].iloc[-1] / start["gold"] - 1) * 100
    ui.kpi_row([
        ("Real interest rate now", f"{real.iloc[-1]:.2f}%", f"10-year, {ui.day(real.index[-1], year=False)}", None),
        ("Month to month: still a mirror", f"{since:+.2f}",
         f"how 3-month changes in gold and the real rate moved together since 2022 (2005-2021: {before:+.2f}; "
         "−1 would be a perfect mirror image)", None),
        ("Year to year: the link broke", f"{rate_rise:+.1f} pts, gold {gold_move:+.0f}%",
         "the real rate and gold since the end of 2021. The old pattern said a jump in rates this big "
         "would sink gold", None),
    ], columns=3)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=both.index, y=both["gold"], name="Gold ($ per ounce)",
                             line=dict(color=COLOR, width=1.6),
                             hovertemplate="%{x|%b %-d, %Y}: $%{y:,.0f}<extra>gold</extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=both.index, y=both["real"], name="10-year real interest rate (right, upside down)",
                             line=dict(color="#1f3a5f", width=1.3),
                             hovertemplate="%{x|%b %-d, %Y}: %{y:.2f}%<extra>real rate</extra>"), secondary_y=True)
    ui.base_layout(fig, 420, hovermode="x unified",
                   legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, font=dict(size=12)))
    fig.update_yaxes(title_text="Gold, $ per ounce", tickprefix="$", tickformat=",.0f", secondary_y=False)
    fig.update_yaxes(title_text="Real interest rate (upside down)", ticksuffix="%", autorange="reversed",
                     tickmode="linear", dtick=1, tickformat=".0f", showgrid=False, secondary_y=True)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gold_real_rate")
    ui.tip("The real rate is drawn upside down, so when both lines rise together gold is doing what falling "
           "real rates would suggest. They tracked closely until 2022; since then gold has climbed even as "
           "real rates rose to their highest since 2008, as central banks (above all China's) bought gold at "
           "a record pace. Real rate: the 10-year yield on inflation-protected Treasuries (TIPS), from FRED. "
           "The cards: from month to month the two still move as mirror images, but the overall level no "
           "longer follows: rates went up a lot and gold went up anyway.", "How to read this")


def fed_section() -> None:
    st.subheader("How gold reacted to Fed rate decisions", anchor=False)
    st.markdown("Every change in the Federal Reserve's target interest rate since late 2004. The **first move "
                "of a new cycle** (a turn in policy) is kept apart from moves that **continue** a cycle. "
                "Cuts tend to happen when the economy is in trouble, so these reactions also reflect the scare "
                "that prompted them.")
    results, paths = data["fed_react"]
    st.markdown("**Average reaction in gold, by type of rate change**")
    ui.comparison_section(prices, results, paths, "decision", fed.CATEGORIES, fed.LABELS, fed.COLORS,
                          key="gold_fed", market="gold", sig=data["sig"], market_key=MARKET)
    st.markdown("**Explore individual rate changes**")
    ui.drilldown_section(results, paths, "decision", fed.CATEGORIES, fed.LABELS, fed.COLORS,
                         table_columns={
                             "effective_date": st.column_config.DateColumn("Effective", format="MMM D, YYYY"),
                             "size_bp": st.column_config.NumberColumn("Change (bp)", format="%+d"),
                             "new_rate": st.column_config.NumberColumn("New rate", format="%.2f%%"),
                             **ui.HORIZON_COLUMNS,
                             "description": st.column_config.TextColumn("What happened", width="large")},
                         key="gold_fed", select_label="Rate change type", market="gold")
    st.caption("Measured from the close two business days before the change took effect, so the reaction is "
               "never missed. Meetings where rates were held aren't included.")


with tab_fed:
    for section in (real_rate_section, fed_section):
        try:
            section()
        except Exception as error:
            st.error(f"This section hit a problem: {error}")
        st.write("")


# Prices & history ---------------------------------------------------------------------
def history_section() -> None:
    st.subheader("Gold prices and gold news spikes", anchor=False)
    cn.price_spike_chart(SPEC, prices, data, gold_archive(), line_name="Gold", y_title="$ per ounce",
                         hover_price="$%{y:,.0f}", since_label="Since 2005", key="gold_history")
    ui.tip("Dots mark days a gold news topic spiked to at least 3× its normal coverage (from 2015). Click one "
           "to see the biggest stories that day and what gold did next. Prices are daily closes worked out "
           "from the GLD gold fund (it holds gold bars), in $ per ounce.", "How to read this")

    st.write("")
    st.markdown("**How gold usually moves in each month**")
    pattern = gs.monthly_pattern(prices, since="2005-01-01")
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    this_month = pd.Timestamp.now().month
    fig = go.Figure(go.Bar(
        x=[names[m - 1] for m in pattern.index], y=pattern["typical"],
        marker_color=["#1f3a5f" if m == this_month else ("#1d8a5e" if v >= 0 else "#c43a39")
                      for m, v in zip(pattern.index, pattern["typical"])],
        customdata=pattern[["rose", "years"]].values,
        hovertemplate="%{x}: typical %{y:+.1f}% · rose in %{customdata[0]:.0f}% of %{customdata[1]} years<extra></extra>"))
    ui.base_layout(fig, 300, yaxis_ticksuffix="%", yaxis_title="Typical change in the month", showlegend=False)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gold_months")
    ui.tip(f"Gold's typical (median) change from the end of one month to the end of the next, since 2005. "
           f"This month ({names[this_month - 1]}) is the dark bar. Gold rose in most years since 2005, so most "
           "bars are green: compare them with each other, not with zero. Hover to see how often gold rose.",
           "How to read this")


with tab_history:
    try:
        history_section()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

with tab_review:
    try:
        gold_review.render(data, gold_closes(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H")))
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

with tab_cond:
    try:
        table, extended, added = gold_conditions(f"{prices.index[-1]}-{len(prices)}-{real.index[-1]}")
        conditions.show(table, extended, added, conditions.GOLD)
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

st.markdown("<div class='footer'><b>Market Tracker</b> is an independent research project. Nothing here is "
            "investment advice, and past reactions are no guarantee of future ones. Data: Yahoo Finance (GLD "
            "closes and live gold futures), FRED / Federal Reserve, Media Cloud, publishers' news feeds, "
            "Benzinga via Alpaca.</div>", unsafe_allow_html=True)
