"""
The natural gas site (the /gas page).

  header   live Henry Hub price, the next storage report, the latest report's
           surprise, and the gas story getting the most extra coverage
  News     Today: why gas moved, the 2-week weather outlook, gas news topics
           (click one for its stories), what's coming up, and the latest gas
           headlines, each with what Henry Hub did after similar past stories.
           Also: Like this before, Topics over time, and Search (commodity_news.py)
  Week in review  how gas moved each week, the storage report, what made the
           news, and what history suggested vs what happened
  Storage  storage against the last 5 years, and the weekly EIA report: how
           prices reacted to each size of surprise since 2015
  Prices & seasons  the storage season, the futures curve (winter premium),
           how gas usually moves each month, and prices since 2010
  Market conditions  today's readings (trend, volatility, storage, vs a year
           ago) against history, and the past days most like today
  Storylines  big gas stories that come back in waves (Europe's crisis,
           Russian pipelines, LNG exports, winter storms, AI power demand)

The machinery is shared with the oil site: news.py (topics and spikes),
event_study.py (price reactions), markets.py (is a pattern real?), ui.py.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import alerts
import conditions
import daily_move as dm
import event_study as es
import fetch_prices
import commodity_news as cn
import gas_review
import gas_storage as gs
import glossary
import live_prices
import market_news as mn
import markets as mk
import mediacloud_news
import news
import news_feeds as nf
import news_page
import signals as sg
import storylines_page
import ui
import weather

ui.apply_styles()

MARKET = "NATGAS"
SPEC = cn.GAS          # the shared News tab, set up for gas


# Data ---------------------------------------------------------------------------
@st.cache_resource(ttl=6 * 60 * 60, show_spinner="Loading natural gas prices and history...")
def get_data() -> dict:
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
    prices = es.load_prices(MARKET)
    try:
        gs.download_storage()
    except Exception as error:
        print(f"Storage download failed, using saved data: {error}")
    storage = gs.build_events(gs.load_storage())
    timelines = mediacloud_news.load(mediacloud_news.GAS_PATH)
    spikes = news.all_spikes(timelines) if not timelines.empty else pd.DataFrame()
    return {
        "prices": prices,
        "storage": storage,
        "storage_react": es.compute_results(prices, storage),
        "timelines": timelines,
        "spikes": spikes,
        "spike_react": es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {}),
        # Typical (median) moves: spot gas has rare huge spikes on very cold
        # days (+380% in a week in January 2024) that would swamp averages
        "sig": mk.Significance({MARKET: prices}, center="median"),
    }


@st.cache_data(ttl=5 * 60, show_spinner=False)
def live_quote():
    return live_prices.quote(MARKET)


@st.cache_data(ttl=30 * 60, show_spinner=False)
def gas_curve(hour: str) -> pd.DataFrame:
    return sg.curve(MARKET, months=24)      # shared by all visitors, refreshed every 30 min


@st.cache_data(ttl=60 * 60, show_spinner=False)
def weather_outlook(hour: str) -> dict | None:
    try:
        return weather.outlook()
    except Exception as error:
        print(f"Weather unavailable: {error!r}")
        return None


@st.cache_data(ttl=30 * 60, show_spinner=False)
def recent_closes(hour: str) -> pd.Series:
    return live_prices.daily_closes(MARKET, span="6mo")


@st.cache_data(ttl=30 * 60, show_spinner=False)
def conditions_table(version: str) -> tuple[pd.DataFrame, pd.Series, int]:
    """Market conditions for every day up to today: the official prices
    carried up to today with futures (they are published about a week late)."""
    extended, added = live_prices.extend(prices, MARKET)
    return conditions.gas_table(extended, gs.vs_five_year_history(gs.load_storage())), extended, added


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def news_archive() -> pd.DataFrame:
    return mn.load_archive()


def gas_headlines() -> pd.DataFrame:
    """Recent articles about natural gas from the publishers' feeds."""
    return cn.live_headlines(SPEC.key)


data = get_data()
prices = data["prices"]
heat = news.current_heat(data["timelines"]) if not data["timelines"].empty else pd.DataFrame()

# Header -------------------------------------------------------------------------
ui.back_link()
now = pd.Timestamp.now(tz="America/New_York")
left, right = st.columns([2, 1], vertical_alignment="top")
left.markdown(
    f'<div class="dateline">{now:%A}, {now:%B} {now.day}, {now:%Y}</div>'
    f'<div class="masthead">{ui.LOGO}<div><div class="wordmark">Natural Gas Tracker</div>'
    '<div class="dek">The news that moves U.S. natural gas, set against similar moments in the past '
    'and what prices did next.</div></div></div>', unsafe_allow_html=True)
actions = right.container(key="top_actions")
if actions.button("Terminology", key="gas_glossary", help="The words the gas market uses, in plain English."):
    glossary.show_gas()
actions.link_button("Spike alerts", alerts.GAS_SUBSCRIBE_URL, width="stretch",
                    help="Free push notifications (ntfy app or browser) when a natural gas news topic starts "
                         "spiking, with what happened after past spikes, plus a Saturday week in review.")
st.write("")

q = live_quote()
if q:
    change = q["change_pct"] or 0
    t = q["time"]
    clock = f"{t.hour % 12 or 12}:{t:%M} {'pm' if t.hour >= 12 else 'am'} ET"
    price_card = ("Henry Hub gas", f"${q['price']:.2f}", f"{'▲' if change >= 0 else '▼'} {change:+.1f}% · {clock}",
                  "#1d8a5e" if change >= 0 else "#c43a39")
else:
    price_card = ("Henry Hub gas", f"${prices.iloc[-1]:.2f}",
                  f"daily spot price, {ui.day(prices.index[-1], year=False)}", None)
upcoming_reports = gs.next_reports(now.tz_localize(None))
next_report = upcoming_reports[0] if upcoming_reports else None
latest = data["storage"].iloc[-1]
busy = heat[heat["enough"]] if not heat.empty else heat
story = (("Biggest gas story", busy.iloc[0]["label"], f"{busy.iloc[0]['heat']:.1f}× its normal news coverage", None)
         if len(busy) else ("Biggest gas story", "Quiet", "no topic stands out", None))
ui.kpi_row([
    price_card,
    ("Next storage report", ui.day(next_report, year=False, weekday=True) if next_report else "—",
     "10:30am ET (expected)", None),
    ("Latest report", gs.LABELS[latest["category"]],
     f"{ui.day(latest['date'], year=False)}: surprise {latest['surprise_bcf']:+.0f} Bcf", gs.COLORS[latest["category"]]),
    story,
])
st.caption(f"Live price: Henry Hub front-month futures, about 10 minutes delayed. Charts use the official daily spot "
           f"price (latest {ui.day(prices.index[-1], year=False)}).")
st.write("")

tab_news, tab_review, tab_storage, tab_history, tab_cond, tab_stories = st.tabs(
    ["News", "Week in review", "Storage", "Prices & seasons", "Market conditions", "Storylines"])


# News ---------------------------------------------------------------------------------
def why_today() -> None:
    cn.why_today(SPEC, q, prices, gas_headlines(), heat, headline_rows)


def weather_section() -> None:
    view = weather_outlook(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H"))
    st.subheader("The weather outlook", anchor=False)
    if view is None:
        st.info("The weather forecast isn't available right now. Try again later.")
        return
    title, detail, effect = weather.reading(view)
    measure = view["measure"]
    word = "heating" if measure == "hdd" else "cooling"
    both = (view["week1"] + view["week2"]) / 2
    bullish = both > 5
    color = "#1d8a5e" if bullish else "#c43a39" if both < -5 else None
    ui.kpi_row([
        ("Next 2 weeks", title.split(":")[0], effect, color),
        ("Days 1-7", f"{view['week1']:+.0f}%", f"{word} demand vs normal", None),
        ("Days 8-14", f"{view['week2']:+.0f}%", f"{word} demand vs normal (less certain)", None),
    ], columns=3)
    days = view["days"]
    past, ahead = days[~days["forecast"]], days[days["forecast"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=past.index, y=past[measure], name="Past week", marker_color="#c9c7bd",
                         hovertemplate="%{x|%a %b %-d}: %{y:.1f}<extra>past week</extra>"))
    fig.add_trace(go.Bar(x=ahead.index, y=ahead[measure], name="Forecast",
                         marker_color="#3b82f6" if measure == "hdd" else "#f97316",
                         hovertemplate="%{x|%a %b %-d}: %{y:.1f}<extra>forecast</extra>"))
    fig.add_trace(go.Scatter(x=days.index, y=days[f"{measure}_normal"], name="Normal (2015-2024)", mode="lines",
                             line=dict(color="#1d1d1b", width=2, dash="dot"),
                             hovertemplate="%{x|%a %b %-d}: normal %{y:.1f}<extra></extra>"))
    ui.base_layout(fig, 300, hovermode="x unified", barmode="overlay",
                   yaxis_title=f"{'Heating' if measure == 'hdd' else 'Cooling'} degree days")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gas_weather")
    st.caption(detail)
    ui.tip(f"Degree days measure {word} demand: how far each day's average temperature is "
           f"{'below' if measure == 'hdd' else 'above'} 65°F, averaged over 14 big U.S. cities weighted by "
           "population (New York counts for more than Denver). More heating degree days in winter means more gas "
           "burned for heat; in summer, cooling degree days mean air-conditioning and more gas burned at power "
           "plants. Forecast from Open-Meteo; normal is the 2015-2024 average for each date.", "How to read this")


def headline_rows(heads: pd.DataFrame, history: bool = True) -> None:
    """Gas headlines; with `history`, each gets a 'Last time' line (what Henry
    Hub did after similar past stories), when there are enough close matches."""
    cn.headline_rows(SPEC, heads, prices, news_archive(), data["sig"] if history else None)


def topic_cards() -> None:
    cn.topic_cards(SPEC, data, heat, lambda topic, row: cn.topic_dialog(
        SPEC, topic, row, gas_headlines(), news_archive(), lambda rows: headline_rows(rows, history=False)))


def coming_up() -> None:
    st.subheader("Coming up", anchor=False)
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    events = [(d, "EIA gas storage report", "10:30am ET") for d in upcoming_reports[:2]]
    try:
        fed_dates = [d for d in pd.read_csv("events/upcoming.csv", parse_dates=["date"]).query("kind == 'fed'")["date"]
                     if d >= today]
        if fed_dates:
            events.append((fed_dates[0], "Fed rate decision", "2:00pm ET"))
    except Exception:
        pass
    cards = []
    for day, title, hour in sorted(events)[:3]:
        days = (day.normalize() - today).days
        when = "Today" if days == 0 else "Tomorrow" if days == 1 else f"In {days} days"
        cards.append((f"{when} · {day:%a %b} {day.day}", title, hour, None))
    ui.kpi_row(cards, columns=len(cards))
    ui.tip("Storage reports come out on Thursdays (later in weeks with a federal holiday; around Thanksgiving "
           "EIA sometimes publishes early instead).", "About this calendar")


def headlines() -> None:
    st.subheader("Latest gas headlines", anchor=False)
    heads = gas_headlines()
    if heads.empty:
        st.info("No natural gas headlines in the last day or two.")
        return
    headline_rows(heads.head(12))
    ui.tip("Articles from our publishers' news feeds that mention natural gas, LNG or Henry Hub, newest first. "
           "\"Last time\" shows what Henry Hub did the week after past gas stories worded most like it "
           "(only when there are enough close matches); \"See them\" opens them in Like this before.",
           "About these stories")


with tab_news:
    try:
        view = cn.pick_view(SPEC)
        if view == "like":
            cn.like_this_before(SPEC, prices, data["sig"], gas_headlines(), news_archive())
        elif view == "topics":
            cn.topics_view(SPEC, prices, data, news_archive())
        elif view == "search":
            cn.search_view(SPEC, prices, data["sig"], news_archive())
        else:
            why_today()
            st.write("")
            weather_section()
            st.write("")
            topic_cards()
            st.write("")
            coming_up()
            st.write("")
            headlines()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")


# Storage reports -----------------------------------------------------------------------
def five_year_chart() -> None:
    view = gs.five_year_view(gs.load_storage())
    st.subheader("Storage against the last 5 years", anchor=False)
    above = view["vs_average_pct"] >= 0
    ui.kpi_row([
        ("Gas in storage", f"{view['level']:,.0f} Bcf", f"week ending {ui.day(view['week_ending'], year=False)}", None),
        ("vs 5-year average", f"{view['vs_average_pct']:+.1f}%",
         f"{abs(view['vs_average_bcf']):,.0f} Bcf {'more' if above else 'less'} than normal: "
         f"{'plenty of gas (bearish)' if above else 'tighter than normal (bullish)'}",
         "#c43a39" if above else "#1d8a5e"),
        ("vs a year ago", f"{view['vs_last_year_pct']:+.1f}%", "same week last year", None),
        ("5-year range", f"{view['low']:,.0f} to {view['high']:,.0f}", "Bcf, lowest and highest for this week", None),
    ])
    t = view["table"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t["week"], y=t["high"], mode="lines", line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=t["week"], y=t["low"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(15, 118, 110, 0.13)", name=f"5-year range ({view['year'] - 5}-{view['year'] - 1})",
                             hovertemplate="Week %{x}: lowest %{y:,.0f} Bcf<extra></extra>"))
    fig.add_trace(go.Scatter(x=t["week"], y=t["average"], mode="lines", name="5-year average",
                             line=dict(color="#0f766e", width=1.5, dash="dot"),
                             hovertemplate="Week %{x}: average %{y:,.0f} Bcf<extra></extra>"))
    fig.add_trace(go.Scatter(x=t["week"], y=t["last_year"], mode="lines", name=str(view["year"] - 1),
                             line=dict(color="#9a988f", width=1.5),
                             hovertemplate="Week %{x}: %{y:,.0f} Bcf<extra></extra>"))
    fig.add_trace(go.Scatter(x=t["week"], y=t["this_year"], mode="lines+markers", name=str(view["year"]),
                             line=dict(color="#1f3a5f", width=3), marker=dict(size=4),
                             hovertemplate="Week %{x}: %{y:,.0f} Bcf<extra></extra>"))
    month_ticks = [1, 5, 9, 14, 18, 22, 27, 31, 36, 40, 44, 48]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ui.base_layout(fig, 400, hovermode="x unified", yaxis_title="Billion cubic feet (Bcf)")
    fig.update_xaxes(tickvals=month_ticks, ticktext=month_names, range=[1, 52])
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gas_five_year")
    ui.tip("Storage rises from about April to October (injection season) and falls in winter (withdrawal "
           "season). The shaded band is the lowest-to-highest level for each week over the previous 5 years. "
           "Above the average line means more gas than usual; below means less, and a cold winter starting "
           "from below normal is when prices tend to spike.", "How to read this")


with tab_storage:
    try:
        five_year_chart()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")
    st.write("")
    st.subheader("The weekly storage report", anchor=False)
    st.markdown("Every Thursday the EIA reports how much natural gas went into or out of underground storage. "
                "What moves prices is the **surprise**: a smaller injection or bigger withdrawal than normal "
                "for that week means supply is **tighter** (usually bullish); the opposite means it's **looser**. "
                "Normal = the average change in the same week over the previous 5 years.")
    st.markdown(f"**Latest report ({ui.day(latest['date'], weekday=True)}):** {latest['description']}, a surprise of "
                f"**{latest['surprise_bcf']:+.0f} Bcf** → *{gs.LABELS[latest['category']]}*.")
    results, paths = data["storage_react"]
    st.markdown("**Typical reaction in Henry Hub gas, by size of surprise**")
    ui.comparison_section(prices, results, paths, "category", gs.CATEGORIES, gs.LABELS, gs.COLORS, "gas_storage",
                          market="natural gas", sig=data["sig"], market_key=MARKET, center="median")
    if not data["storage"].empty:
        st.markdown("**Recent reports**")
        # the latest reports too: their price moves fill in as the official prices arrive
        recent = data["storage"].sort_values("date", ascending=False).head(12)
        if not results.empty:
            recent = recent.join(results.set_index("date")[["day_1_pct", "day_5_pct"]], on="date")
        else:
            recent = recent.assign(day_1_pct=float("nan"), day_5_pct=float("nan"))
        st.dataframe(pd.DataFrame({
            "Report": recent["date"].values,
            "Change (Bcf)": recent["change_bcf"].values,
            "Normal (Bcf)": recent["normal_bcf"].values,
            "Surprise (Bcf)": recent["surprise_bcf"].values,
            "Verdict": [gs.LABELS[c] for c in recent["category"]],
            "1 day": pd.to_numeric(recent["day_1_pct"], errors="coerce").values,
            "1 week": pd.to_numeric(recent["day_5_pct"], errors="coerce").values,
        }), width="stretch", hide_index=True, column_config={
            "Report": st.column_config.DateColumn(format="MMM D, YYYY"),
            "1 day": st.column_config.NumberColumn(format="%+.1f%%"),
            "1 week": st.column_config.NumberColumn(format="%+.1f%%"),
        })


# Price history ----------------------------------------------------------------------
def season_and_curve() -> None:
    name, explain = gs.season(pd.Timestamp.now())
    st.subheader("Where we are in the gas year", anchor=False)
    st.markdown(f"**{name}.** {explain}")

    st.write("")
    st.markdown("**The futures curve: what gas costs for each month ahead**")
    curve = gas_curve(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H"))
    if curve.empty:
        st.info("The futures curve isn't available right now. It comes from a free price feed that sometimes "
                "doesn't answer; try again later.")
    else:
        winter = curve[curve["month"].dt.month.isin([12, 1, 2])].head(3)
        summer = curve[curve["month"].dt.month.isin([4, 5, 6, 7, 8, 9, 10])].head(7)
        if len(winter) and len(summer):
            w, sm = winter["now"].mean(), summer["now"].mean()
            st.markdown(f"Gas for the coming winter ({winter['month'].iloc[0]:%b %Y} to {winter['month'].iloc[-1]:%b %Y}) "
                        f"costs **${w:.2f}**, against **${sm:.2f}** for next summer: a winter premium of "
                        f"**{(w / sm - 1) * 100:.0f}%**. "
                        + ("That's a big premium: traders expect a tight winter." if w / sm > 1.3 else
                           "A normal-sized premium." if w / sm > 1.1 else
                           "A small premium: traders aren't worried about winter supply."))
        fig = go.Figure()
        for _, r in curve.iterrows():
            if r["month"].month in (12, 1, 2):
                fig.add_vrect(x0=r["month"] - pd.Timedelta(days=15), x1=r["month"] + pd.Timedelta(days=15),
                              fillcolor="rgba(59, 130, 246, 0.08)", line_width=0, layer="below")
        fig.add_trace(go.Scatter(x=curve["month"], y=curve["1 month ago"], mode="lines", name="1 month ago",
                                 line=dict(color="#c9c7bd", width=1.6),
                                 hovertemplate="%{x|%b %Y}: $%{y:.2f}<extra>1 month ago</extra>"))
        fig.add_trace(go.Scatter(x=curve["month"], y=curve["now"], mode="lines+markers", name="Today",
                                 line=dict(color="#0f766e", width=3), marker=dict(size=5),
                                 hovertemplate="%{x|%b %Y}: $%{y:.2f}<extra>today</extra>"))
        ui.base_layout(fig, 340, hovermode="closest", yaxis_tickprefix="$", yaxis_title="$ per MMBtu",
                       xaxis_title="Delivery month")
        fig.update_xaxes(tickformat="%b %Y")
        st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gas_curve")
        ui.tip("Each point is the price agreed today for gas delivered in that month (a futures contract). "
               "Shaded bands are winter months (December to February), when heating demand peaks, so gas for "
               "winter usually costs more: the 'winter premium'. Prices are NYMEX futures, about 10 minutes "
               "delayed.", "How to read this")

    st.write("")
    st.markdown("**How gas usually moves in each month**")
    pattern = gs.monthly_pattern(prices)
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    this_month = pd.Timestamp.now().month
    fig = go.Figure(go.Bar(
        x=[names[m - 1] for m in pattern.index], y=pattern["typical"],
        marker_color=["#1f3a5f" if m == this_month else ("#1d8a5e" if v >= 0 else "#c43a39")
                      for m, v in zip(pattern.index, pattern["typical"])],
        customdata=pattern[["rose", "years"]].values,
        hovertemplate="%{x}: typical %{y:+.1f}% · rose in %{customdata[0]:.0f}% of %{customdata[1]} years<extra></extra>"))
    ui.base_layout(fig, 300, yaxis_ticksuffix="%", yaxis_title="Typical change in the month", showlegend=False)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gas_months")
    ui.tip(f"Henry Hub's typical (median) change from the end of one month to the end of the next, since 2010. "
           f"This month ({names[this_month - 1]}) is the dark bar. Patterns like these are tendencies, not rules: "
           f"in most months gas rose in some years and fell in others (hover to see how often it rose).",
           "How to read this")


with tab_history:
    try:
        season_and_curve()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")
    st.write("")
    st.subheader("Henry Hub prices and gas news spikes", anchor=False)
    try:
        cn.price_spike_chart(SPEC, prices[prices.index >= "2010-01-01"], data, news_archive(),
                             line_name="Henry Hub", y_title="$ per MMBtu", hover_price="$%{y:.2f}",
                             since_label="Since 2010", key="gas_history")
    except Exception as error:
        st.error(f"This section hit a problem: {error}")
    ui.tip("Dots mark days a gas news topic spiked to at least 3× its normal coverage (from 2015). Click one "
           "to see the biggest stories that day and what gas did next. Gas is far more volatile than oil: a 5% "
           "day is ordinary, especially in winter.", "How to read this")

with tab_review:
    try:
        gas_review.render(data, recent_closes(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H")))
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

with tab_cond:
    try:
        table, extended, added = conditions_table(f"{prices.index[-1]}-{len(prices)}-{len(data['storage'])}")
        conditions.show(table, extended, added, conditions.GAS)
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

with tab_stories:
    try:
        storylines_page.render_for("gas", prices, news_archive())
    except Exception as error:
        st.error(f"This section hit a problem: {error}")

st.markdown("<div class='footer'><b>Market Tracker</b> is an independent research project. Nothing here is "
            "investment advice, and past reactions are no guarantee of future ones. Data: U.S. EIA, FRED, Media "
            "Cloud, publishers' news feeds, Yahoo Finance (live futures), Open-Meteo (weather, CC BY 4.0).</div>", unsafe_allow_html=True)
