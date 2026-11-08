"""
The News page: today's oil news -> similar moments in the past -> what the
oil market did next.

Two news sources (see news.py and market_news.py):
  - Worldwide news (GDELT): huge coverage, history since 2017, saved daily.
  - Market news (Alpaca/Benzinga): financial news since 2015, saved in full,
    so headlines and searches work instantly without asking anyone live.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import market_news as mn
import news
import ui

TOPIC_KEYS = list(news.TOPICS)
LABELS = {k: t["label"] for k, t in news.TOPICS.items()}
COLORS = {k: t["color"] for k, t in news.TOPICS.items()}
SOURCE_NAMES = {"gdelt": "Worldwide news (GDELT, since 2017)",
                "market": "Market news (Benzinga, since 2015)"}
EXAMPLES = ['"Strait of Hormuz"', "Houthi", "refinery fire", "Abqaiq", "Libya",
            '"price war"', '"rig count"', "hurricane", "Venezuela", "lockdown"]

SPIKE_TABLE = {
    "spike_day": st.column_config.DateColumn("News spike", format="YYYY-MM-DD"),
    "headline": st.column_config.TextColumn("Main headline that day", width="large"),
    "ratio": st.column_config.NumberColumn("Coverage vs normal", format="%.1fx"),
    "articles": st.column_config.NumberColumn("Articles", format="%d"),
    **ui.HORIZON_COLUMNS,
}


def current_heat(data: dict) -> tuple[pd.DataFrame, str]:
    """Topic heat from worldwide news, or from market news if the worldwide
    data is more than a few days old (e.g. GDELT blocked the daily update)."""
    heat = news.current_heat(data["timelines"])
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    if not heat.empty and heat["last_day"].max() >= today - pd.Timedelta(days=4):
        return heat, "gdelt"
    market = news.current_heat(data["market_timelines"], "market")
    return (market, "market") if not market.empty else (heat, "gdelt")


@st.cache_data(ttl=15 * 60, show_spinner=False)
def latest_headlines(_archive: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """(headlines, live?). Live from Alpaca (fast, our own keys); if that
    fails, the newest saved headlines from the archive."""
    try:
        live = mn.latest()
        if not live.empty:
            return live, True
    except Exception as error:
        print(f"Live headlines unavailable, using saved ones: {error}")
    recent = _archive[_archive["time"] >= _archive["time"].max() - pd.Timedelta(hours=48)]
    return mn.oil_related(recent).sort_values("time", ascending=False), False


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False, max_entries=200)
def search_archive(query: str, _archive: pd.DataFrame, _prices: pd.Series):
    """Search the saved market news archive: instant, no outside requests."""
    match = mn.search_mask(_archive, query)
    t = mn.counts(_archive, match, "search")
    spikes = news.find_spikes(t, source="market", min_articles=3)
    spikes = mn.add_headlines(spikes, _archive,
                              lambda window, spike: mn.search_mask(window, query))
    results, paths = (es.compute_results(_prices, spikes) if not spikes.empty
                      else (pd.DataFrame(), {}))
    recent = _archive[match].sort_values("time", ascending=False).head(8)
    return t, results, paths, recent


def status(heat: float) -> tuple[str, str]:
    if heat >= news.SPIKE_RATIO:
        return "Spiking", "#e34948"
    if heat >= 1.5:
        return "Elevated", "#eda100"
    return "Normal", "#1baf7a"


def coverage_chart(t: pd.DataFrame, spikes: pd.DataFrame, color: str, key: str,
                   source: str = "gdelt") -> None:
    c = news.coverage(t, source)
    share = c.set_index("date")["share_per_million"]
    if source == "market":       # share of the oil news archive, in %
        share, unit, title = share / 1e4, "%{y:.1f}% of oil news", "% of oil news"
        window = 30
    else:
        unit, title, window = "%{y:,.0f} per million articles", "Articles per million", 7
    smooth = share.rolling(window, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=smooth.index, y=smooth.values, mode="lines",
                             name=f"Coverage ({window}-day average)",
                             line=dict(color=color, width=1.6),
                             hovertemplate="%{x|%b %d, %Y}: " + unit + "<extra></extra>"))
    if not spikes.empty:
        at = smooth.reindex(spikes["spike_day"]).values
        fig.add_trace(go.Scatter(
            x=spikes["spike_day"], y=at, mode="markers", name="News spike",
            marker=dict(size=9, color="#ffffff", line=dict(color="#1d1d1b", width=2)),
            customdata=spikes[["description"]].values,
            hovertemplate="<b>%{x|%b %d, %Y}</b><br>%{customdata[0]}<extra></extra>"))
    ui.base_layout(fig, 300, hovermode="closest", yaxis_title=title)
    st.plotly_chart(fig, width="stretch", key=key)


def headline_list(heads: pd.DataFrame) -> None:
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for _, h in heads.iterrows():
        hours = max(int((now - h["time"]).total_seconds() // 3600), 0)
        ago = f"{hours}h ago" if hours < 48 else f"{h['time']:%b %d, %Y}"
        chips = "".join(ui.chip(LABELS[t], COLORS[t]) for t in h["topics"])
        rows.append(
            f'<div class="headline"><a href="{html.escape(h["url"])}" target="_blank">'
            f'{html.escape(h["headline"])}</a><div class="meta">{chips}'
            f'{html.escape(h["source"])} · {ago}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


def render(prices: pd.Series, data: dict) -> None:
    timelines, archive = data["timelines"], data["archive"]
    heat, heat_source = current_heat(data)
    results = data["news"][0] if heat_source == "gdelt" else data["market_news"][0]

    # ---- 1. What's in the news now ------------------------------------------
    if not heat.empty:
        ui.eyebrow("In the news now")
        st.subheader("Which oil stories are making headlines, and what happened last time", anchor=False)
        st.caption(f"Coverage over the last 3 days compared with normal, from "
                   f"{SOURCE_NAMES[heat_source].split(' (')[0].lower()} (data to "
                   f"{heat['last_day'].max():%b %d, %Y}). For each topic: what Brent did "
                   "in the week after past news spikes.")
        cols = st.columns(4)
        for i, (_, row) in enumerate(heat.iterrows()):
            past = results[results["topic"] == row["topic"]]
            label, color = status(row["heat"])
            with cols[i % 4].container(border=True, height="stretch"):
                st.markdown(ui.chip(label, color), unsafe_allow_html=True)
                st.markdown(f"**{row['label']}**")
                st.markdown(f"<span style='font-size:1.5rem;font-weight:600'>{row['heat']:.1f}×</span>"
                            f" <span style='color:#898781'>normal coverage</span>",
                            unsafe_allow_html=True)
                if len(past):
                    week = past["day_5_pct"]
                    st.caption(f"After {len(past)} past spikes, Brent averaged "
                               f"**{week.mean():+.1f}%** over the next week and rose "
                               f"{(week > 0).mean():.0%} of the time.")
                else:
                    st.caption("No past spikes to compare with yet.")
        st.write("")

    # ---- 2. Latest headlines ---------------------------------------------------
    ui.eyebrow("Latest headlines")
    st.subheader("Today's oil news, tagged by topic", anchor=False)
    heads, is_live = latest_headlines(archive) if not archive.empty else (pd.DataFrame(), False)
    if not heads.empty:
        if not is_live:
            st.caption(f"The live feed didn't respond, so these are the newest saved "
                       f"headlines (to {heads['time'].max():%b %d, %H:%M} UTC).")
        heads = heads.assign(tagged=heads["topics"].str.len() > 0).sort_values(
            ["tagged", "time"], ascending=[False, False]).head(15)
        headline_list(heads)
        st.caption("Market news from Benzinga via Alpaca. Click to read the original article.")
    else:
        st.info("Headlines are temporarily unavailable; the rest of the page works as normal.")

    # ---- 3. Explore a topic -----------------------------------------------------
    st.write("")
    ui.eyebrow("Explore a topic")
    st.subheader("Past news spikes and how oil reacted", anchor=False)
    explore_topic(prices, data)

    # ---- 4. Compare all topics ------------------------------------------------
    news_results, news_paths = data["news"]
    if not news_results.empty:
        st.write("")
        ui.eyebrow("All topics")
        st.subheader("Average Brent move after a news spike, by topic", anchor=False)
        available = [k for k in TOPIC_KEYS if k in set(news_results["topic"])]
        ui.comparison_section(prices, news_results, news_paths, "topic", available,
                              LABELS, COLORS, key="news_cmp")
        st.caption("Based on worldwide news spikes (GDELT).")

    # ---- 5. Search the archive ---------------------------------------------------
    st.write("")
    ui.eyebrow("Search the past")
    st.subheader("Look up any news theme", anchor=False)
    search_section(prices, archive)


@st.fragment
def explore_topic(prices, data) -> None:
    c1, c2 = st.columns([1, 1])
    topic = c1.selectbox("Topic", TOPIC_KEYS, format_func=lambda k: LABELS[k], key="news_topic")
    source = c2.segmented_control("News source", list(SOURCE_NAMES), default="gdelt",
                                  format_func=lambda k: SOURCE_NAMES[k],
                                  key="news_source") or "gdelt"
    timelines = data["timelines"] if source == "gdelt" else data["market_timelines"]
    results, paths = data["news"] if source == "gdelt" else data["market_news"]
    t = timelines[timelines["topic"] == topic]
    if t.empty:
        st.info("No data for this topic from this source yet.")
        return
    spikes = results[results["topic"] == topic] if not results.empty else results
    if source == "gdelt":
        st.caption(f"Worldwide news search used: `{news.TOPICS[topic]['query']}`")
    else:
        st.caption("Share of all saved oil-market news whose headline matches this topic.")
    coverage_chart(t, spikes, COLORS[topic], key="news_cov", source=source)
    st.markdown(f"**Brent after each of the {len(spikes)} news spikes**")
    ui.event_paths(spikes, paths, COLORS[topic], SPIKE_TABLE, key="news_topic_paths")


@st.fragment
def search_section(prices, archive) -> None:
    if archive.empty:
        st.info("The news archive is still being built; please check back soon.")
        return
    st.caption(f"Searches {len(archive):,} oil-market news stories since "
               f"{archive['time'].min():%Y}, instantly. We find the days a theme suddenly "
               "dominated the news and show what Brent did next. Put exact phrases in "
               'quotes; use OR for alternatives, e.g. `Libya OR Nigeria`.')
    pick = st.pills("Try one", EXAMPLES, key="news_example")
    with st.form("news_search", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        typed = c1.text_input("News theme", placeholder='"Strait of Hormuz"')
        submitted = c2.form_submit_button("Search history", width="stretch", type="primary")
    query = typed.strip() if submitted and typed.strip() else pick
    if not query:
        return
    t, results, paths, recent = search_archive(query, archive, prices)
    if recent.empty:
        st.info(f"No stories found for {query}. Try fewer or simpler words.")
        return
    st.markdown(f"**{int(t['articles'].sum()):,} stories mention {html.escape(query)}**")
    spikes = results if not results.empty else pd.DataFrame(columns=["spike_day", "description"])
    coverage_chart(t, spikes, "#2a78d6", key="news_search_cov", source="market")
    if results.empty:
        st.info("This theme never spiked sharply enough to count as a news event "
                f"(needs {news.SPIKE_RATIO:.0f}× its normal coverage on a busy day).")
    else:
        week = results["day_5_pct"]
        c1, c2, c3 = st.columns(3)
        c1.metric("News spikes found", len(results), border=True)
        c2.metric("Brent a week later: average", f"{week.mean():+.1f}%", border=True)
        c3.metric("Brent rose afterwards", f"{(week > 0).mean():.0%}", border=True)
        ui.event_paths(results, paths, "#2a78d6", SPIKE_TABLE, key="news_search_paths")
    with st.expander("Most recent matching stories"):
        headline_list(recent)
