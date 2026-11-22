"""
The natural gas site (the /gas page).

  header   live Henry Hub price, the next storage report, the latest report's
           surprise, and the gas story getting the most extra coverage
  News     gas news topics with what Henry Hub did after past spikes, what's
           coming up, and the latest gas headlines
  Storage  the weekly EIA storage report: how prices reacted to each size of
           surprise since 2015
  History  Henry Hub prices since 2010, with past gas news spikes marked

The machinery is shared with the oil site: news.py (topics and spikes),
event_study.py (price reactions), markets.py (is a pattern real?), ui.py.
"""

import html
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import fetch_prices
import gas_storage as gs
import live_prices
import markets as mk
import mediacloud_news
import news
import news_feeds as nf
import news_page
import ui

ui.apply_styles()

MARKET = "NATGAS"
# ("gas prices" alone usually means petrol at the pump, so it isn't matched)
GAS_TERMS = re.compile(r"natural gas|\bnat ?gas\b|\blng\b|henry hub|gas (storage|field|pipeline|export|supplies)"
                       r"|gazprom|nord stream|\bttf\b|liquefied", re.I)


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
        "sig": mk.Significance({MARKET: prices}),
    }


@st.cache_data(ttl=5 * 60, show_spinner=False)
def live_quote():
    return live_prices.quote(MARKET)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def gas_headlines() -> pd.DataFrame:
    """Recent articles about natural gas from the publishers' feeds."""
    try:
        pool = nf.fetch(oil_only=False)
    except Exception as error:
        print(f"News feeds unavailable: {error}")
        pool = pd.DataFrame(columns=nf.COLUMNS)
    if pool.empty:
        saved = news_page.feed_archive()
        since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)
        pool = saved[saved["time"] >= since] if not saved.empty else saved
    if pool.empty:
        return pool
    text = pool["headline"].fillna("") + " " + pool["summary"].fillna("")
    gas = pool[text.str.contains(GAS_TERMS)].copy()
    gas["topics"] = gas["headline"].map(lambda h: news.classify_gas(str(h)))
    return gas.sort_values("time", ascending=False).drop_duplicates("headline")


data = get_data()
prices = data["prices"]
heat = news.current_heat(data["timelines"]) if not data["timelines"].empty else pd.DataFrame()

# Header -------------------------------------------------------------------------
ui.back_link()
now = pd.Timestamp.now(tz="America/New_York")
st.markdown(
    f'<div class="dateline">{now:%A}, {now:%B} {now.day}, {now:%Y}</div>'
    f'<div class="masthead">{ui.LOGO}<div><div class="wordmark">Natural Gas Tracker</div>'
    '<div class="dek">The news that moves U.S. natural gas, set against similar moments in the past '
    'and what prices did next.</div></div></div>', unsafe_allow_html=True)
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

tab_news, tab_storage, tab_history = st.tabs(["News", "Storage reports", "Price history"])


# News ---------------------------------------------------------------------------------
def topic_cards() -> None:
    if heat.empty:
        st.info("Gas news coverage is still being collected. It's refreshed every 3 hours.")
        return
    st.subheader("What's in the gas news", anchor=False)
    st.caption(f"Coverage of each topic over the last 3 days compared with normal, in about 1,600 news sites "
               f"(data to {ui.day(heat['last_day'].max())}). For each: what Henry Hub did the week after past spikes.")
    results = data["spike_react"][0]
    st.html(ui.CARD_CSS)  # the card styling the oil site uses
    cols = st.columns(len(heat))
    for col, (_, row) in zip(cols, heat.iterrows()):
        label, color, tint = news_page.status(row["heat"], row["enough"], row["big_enough"])
        info = news.topic_info(row["topic"])
        with col.container(border=True, height="stretch"):
            number_color = color if label in ("Spiking", "Elevated") else "#1d1d1b"
            st.markdown(ui.status_line(label, color) + f"<div class='card-title'>{info['label']}</div>"
                        f"<span class='heat-num' style='color:{number_color}'>{row['heat']:.1f}×</span>"
                        " <span class='heat-unit'>normal coverage</span>" + ui.heat_gauge(row["heat"], color),
                        unsafe_allow_html=True)
            past = results[results["topic"] == row["topic"]] if not results.empty else results
            if len(past):
                week = past["day_5_pct"]
                p = data["sig"].p_value(MARKET, 5, week)
                verdict = data["sig"].verdict(p, week.notna().sum())
                st.markdown("<div class='card-rule'></div>"
                            f"<div class='eyebrow' style='margin-top:0.4rem'>After {len(past)} past spikes</div>"
                            f"<div class='past'>Gas <b>{week.mean():+.1f}%</b> the next week · rose "
                            f"{(week > 0).mean():.0%} of the time</div>"
                            + ui.verdict_badge(verdict, ui.verdict_tip(verdict, p, int(week.notna().sum()),
                                                                      "week for gas"), quiet=True),
                            unsafe_allow_html=True)
            else:
                st.caption("No past spikes to compare with yet.")


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
    rows = []
    for _, h in heads.head(12).iterrows():
        title = html.escape(ui.headline_case(str(h["headline"])))
        link = f'<a href="{html.escape(str(h["url"]))}" target="_blank" rel="noopener">{title}</a>'
        summary = html.escape(str(h.get("summary") or ""))[:220]
        chips = "".join(ui.chip(news.topic_info(t)["label"], news.topic_info(t)["color"]) for t in h["topics"])
        rows.append(f'<div class="headline">{link}<div class="summary">{summary}</div>'
                    f'<div class="meta">{chips}<span class="publisher">{html.escape(str(h["source"]))}</span>'
                    f' · {news_page._ago(h["time"])}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    ui.tip("Articles from our publishers' news feeds that mention natural gas, LNG or Henry Hub, newest first.",
           "About these stories")


with tab_news:
    try:
        topic_cards()
        st.write("")
        coming_up()
        st.write("")
        headlines()
    except Exception as error:
        st.error(f"This section hit a problem: {error}")


# Storage reports -----------------------------------------------------------------------
with tab_storage:
    st.subheader("The weekly storage report", anchor=False)
    st.markdown("Every Thursday the EIA reports how much natural gas went into or out of underground storage. "
                "What moves prices is the **surprise**: a smaller injection or bigger withdrawal than normal "
                "for that week means supply is **tighter** (usually bullish); the opposite means it's **looser**. "
                "Normal = the average change in the same week over the previous 5 years.")
    st.markdown(f"**Latest report ({ui.day(latest['date'], weekday=True)}):** {latest['description']}, a surprise of "
                f"**{latest['surprise_bcf']:+.0f} Bcf** → *{gs.LABELS[latest['category']]}*.")
    results, paths = data["storage_react"]
    st.markdown("**Average reaction in Henry Hub gas, by size of surprise**")
    ui.comparison_section(prices, results, paths, "category", gs.CATEGORIES, gs.LABELS, gs.COLORS, "gas_storage",
                          market="natural gas", sig=data["sig"], market_key=MARKET)
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
with tab_history:
    st.subheader("Henry Hub prices and gas news spikes", anchor=False)
    since = prices[prices.index >= "2010-01-01"]
    fig = go.Figure(go.Scatter(x=since.index, y=since.values, mode="lines", name="Henry Hub",
                               line=dict(color="#0f766e", width=1.4),
                               hovertemplate="%{x|%b %-d, %Y}: $%{y:.2f}<extra></extra>"))
    spikes = data["spikes"]
    if not spikes.empty:
        for topic, group in spikes.groupby("topic"):
            info = news.topic_info(topic)
            on = since.reindex(group["date"], method="nearest")
            fig.add_trace(go.Scatter(x=on.index, y=on.values, mode="markers", name=info["label"],
                                     marker=dict(color=info["color"], size=9, line=dict(color="white", width=1)),
                                     hovertemplate=f"{info['label']}<br>%{{x|%b %-d, %Y}}<extra></extra>"))
    ui.base_layout(fig, 480, hovermode="closest", yaxis_tickprefix="$", yaxis_title="$ per MMBtu",
                   legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, font=dict(size=12)))
    fig.update_xaxes(range=[since.index[-1] - pd.DateOffset(years=5), since.index[-1] + pd.Timedelta(days=20)],
                     rangeselector=ui.range_buttons([1, 5], "Since 2010", y=1.0))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="gas_history")
    ui.tip("Dots mark days a gas news topic spiked to at least 3× its normal coverage (from 2015). Gas is far "
           "more volatile than oil: a 5% day is ordinary, especially in winter.", "How to read this")

st.markdown("<div class='footer'><b>Market Tracker</b> is an independent research project. Nothing here is "
            "investment advice, and past reactions are no guarantee of future ones. Data: U.S. EIA, FRED, Media "
            "Cloud, publishers' news feeds, Yahoo Finance (live futures).</div>", unsafe_allow_html=True)
