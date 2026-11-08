"""
The News page: today's oil news -> similar moments in the past -> what the
oil market did next. (Data and spike logic live in news.py.)
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import news
import ui

TOPIC_KEYS = list(news.TOPICS)
LABELS = {k: t["label"] for k, t in news.TOPICS.items()}
COLORS = {k: t["color"] for k, t in news.TOPICS.items()}

SPIKE_TABLE = {
    "spike_day": st.column_config.DateColumn("News spike", format="YYYY-MM-DD"),
    "ratio": st.column_config.NumberColumn("Coverage vs normal", format="%.1fx"),
    "articles": st.column_config.NumberColumn("Articles that day", format="%d"),
    **ui.HORIZON_COLUMNS,
}


@st.cache_data(ttl=30 * 60, show_spinner=False)
def latest_headlines() -> tuple[pd.DataFrame, bool]:
    """(headlines, live?). One quick try at GDELT - never more than ~10 seconds.
    If GDELT is busy, fall back to the headlines a GitHub job saves every few
    hours. Either result is cached for 30 minutes so GDELT isn't hammered."""
    try:
        live = news.headlines(quick=True)
        if not live.empty:
            return live, True
    except Exception as error:
        print(f"Live headlines unavailable, using saved ones: {error}")
    return news.load_saved_headlines(), False


def theme_results(t: pd.DataFrame, prices: pd.Series):
    if t.empty:
        return t, pd.DataFrame(), {}
    spikes = news.find_spikes(t.assign(topic="search"))
    results, paths = es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {})
    return t, results, paths


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def search_theme(query: str, prices: pd.Series):
    """A live search of GDELT (can be turned away when GDELT is busy)."""
    return theme_results(news.timeline(query, quick=True), prices)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def saved_themes() -> pd.DataFrame:
    return news.load_themes()


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def saved_theme(key: str, prices: pd.Series):
    """A theme downloaded ahead of time by the daily GitHub job: instant."""
    themes = saved_themes()
    return theme_results(themes[themes["topic"] == key].drop(columns="topic"), prices)


def _plain(text: str) -> str:
    return " ".join(text.lower().replace('"', " ").split())


def matching_theme(query: str, available: list[str]) -> str | None:
    """If the typed search is one of the saved themes, use the saved copy."""
    q = _plain(query)
    for key in available:
        label, theme_query = news.THEMES[key]
        if q in (_plain(label), _plain(theme_query), _plain(key.replace("_", " "))):
            return key
    return None


def status(heat: float) -> tuple[str, str]:
    if heat >= news.SPIKE_RATIO:
        return "Spiking", "#e34948"
    if heat >= 1.5:
        return "Elevated", "#eda100"
    return "Normal", "#1baf7a"


def coverage_chart(t: pd.DataFrame, spikes: pd.DataFrame, color: str, key: str) -> None:
    c = news.coverage(t)
    smooth = c.set_index("date")["share_per_million"].rolling(7, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=smooth.index, y=smooth.values, mode="lines",
                             name="Coverage (7-day average)", line=dict(color=color, width=1.6),
                             hovertemplate="%{x|%b %d, %Y}: %{y:,.0f} per million articles<extra></extra>"))
    if not spikes.empty:
        at = smooth.reindex(spikes["spike_day"]).values
        fig.add_trace(go.Scatter(
            x=spikes["spike_day"], y=at, mode="markers", name="News spike",
            marker=dict(size=9, color="#ffffff", line=dict(color="#1d1d1b", width=2)),
            customdata=spikes[["description"]].values,
            hovertemplate="<b>%{x|%b %d, %Y}</b><br>%{customdata[0]}<extra></extra>"))
    ui.base_layout(fig, 300, hovermode="closest",
                   yaxis_title="Articles per million")
    st.plotly_chart(fig, width="stretch", key=key)


def render(prices: pd.Series, timelines: pd.DataFrame, results: pd.DataFrame,
           paths: dict) -> None:
    heat = news.current_heat(timelines)
    # Only offer topics whose history has been downloaded so far
    available = [k for k in TOPIC_KEYS if k in set(timelines["topic"])]
    if heat.empty:
        st.info("The news history hasn't been downloaded yet. It's refreshed once a day; "
                "please check back soon.")
        search_section(prices)
        return

    # ---- 1. What's in the news now ------------------------------------------
    ui.eyebrow("In the news now")
    st.subheader("Which oil stories are making headlines, and what happened last time")
    st.caption(f"Coverage over the last 3 days compared with normal (data to "
               f"{heat['last_day'].max():%b %d, %Y}). For each topic: what Brent did in the "
               "week after past news spikes.")
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

    # ---- 2. Latest headlines ---------------------------------------------------
    st.write("")
    ui.eyebrow("Latest headlines")
    st.subheader("Today's oil news, tagged by topic")
    heads, is_live = latest_headlines()
    if not heads.empty:
        if not is_live:
            st.caption(f"The live news feed is busy, so these are recently saved headlines "
                       f"(newest from {heads['time'].max():%b %d, %H:%M} UTC).")
        heads = heads.assign(tagged=heads["topics"].str.len() > 0).sort_values(
            ["tagged", "time"], ascending=[False, False]).head(15)
        now = pd.Timestamp.now(tz="UTC")
        rows = []
        for _, h in heads.iterrows():
            hours = max(int((now - h["time"]).total_seconds() // 3600), 0)
            chips = "".join(ui.chip(LABELS[t], COLORS[t]) for t in h["topics"])
            rows.append(
                f'<div class="headline"><a href="{html.escape(h["url"])}" target="_blank">'
                f'{html.escape(h["title"])}</a><div class="meta">{chips}'
                f'{html.escape(h["source"])} · {hours}h ago</div></div>')
        st.markdown("".join(rows), unsafe_allow_html=True)
        st.caption("Headlines from the GDELT Project. Click to read the original article.")
    else:
        st.info("Headlines are temporarily unavailable because the news feed is busy. "
                "They'll appear again shortly; the rest of the page works as normal.")

    # ---- 3. Explore a topic -----------------------------------------------------
    st.write("")
    ui.eyebrow("Explore a topic")
    st.subheader("Past news spikes and how oil reacted")
    explore_topic(prices, timelines, results, paths, available)

    # ---- 4. Compare all topics ------------------------------------------------
    st.write("")
    ui.eyebrow("All topics")
    st.subheader("Average Brent move after a news spike, by topic")
    ui.comparison_section(prices, results, paths, "topic", available, LABELS, COLORS,
                          key="news_cmp")

    # ---- 5. Search your own theme ----------------------------------------------
    st.write("")
    ui.eyebrow("Search the past")
    st.subheader("Look up any news theme")
    search_section(prices)


@st.fragment
def explore_topic(prices, timelines, results, paths, available) -> None:
    topic = st.selectbox("Topic", available, format_func=lambda k: LABELS[k], key="news_topic")
    t = timelines[timelines["topic"] == topic]
    spikes = results[results["topic"] == topic]
    st.caption(f"Search used: `{news.TOPICS[topic]['query']}`")
    coverage_chart(t, spikes, COLORS[topic], key="news_cov")
    st.markdown(f"**Brent after each of the {len(spikes)} news spikes**")
    ui.event_paths(spikes, paths, COLORS[topic], SPIKE_TABLE, key="news_topic_paths")


@st.fragment
def search_section(prices) -> None:
    themes = saved_themes()
    available = [k for k in news.THEMES if k in set(themes["topic"])]
    st.caption("Find the days a theme suddenly dominated worldwide news (since 2017) and "
               "see what Brent did next. Popular themes load instantly; anything else is "
               "searched live.")
    pick = None
    if available:
        pick = st.pills("Popular themes", available, format_func=lambda k: news.THEMES[k][0],
                        key="theme_pick")
    with st.form("news_search", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        query = c1.text_input("Or type your own theme (put exact phrases in quotes)",
                              placeholder='"Abqaiq" or refinery strike')
        submitted = c2.form_submit_button("Search history", width="stretch", type="primary")

    if submitted and query.strip():
        key = matching_theme(query, available)
        if key:
            t, results, paths = saved_theme(key, prices)
        else:
            with st.spinner("Searching the news archive (can take up to ~30 seconds)..."):
                try:
                    t, results, paths = search_theme(query.strip(), prices)
                except Exception as error:
                    print(f"Live search failed: {error}")
                    st.warning(
                        "The news archive (GDELT) is busy right now. It's a free service that "
                        "limits how often it can be searched, and this website shares its "
                        "connection with other sites, so live searches are sometimes turned "
                        "away. Please try again in a minute or two, or pick one of the "
                        "popular themes above, which always load instantly.")
                    return
    elif pick:
        t, results, paths = saved_theme(pick, prices)
    else:
        return
    show_search_results(t, results, paths)


def show_search_results(t: pd.DataFrame, results: pd.DataFrame, paths: dict) -> None:
    if t.empty or t["articles"].sum() == 0:
        st.info("No coverage found. Try fewer or simpler words.")
        return
    spikes = results if not results.empty else pd.DataFrame(columns=["spike_day", "description"])
    coverage_chart(t, spikes, "#2a78d6", key="news_search_cov")
    if results.empty:
        st.info("This theme never spiked sharply enough to count as a news event "
                f"(needs {news.SPIKE_RATIO:.0f}x normal coverage).")
        return
    week = results["day_5_pct"]
    c1, c2, c3 = st.columns(3)
    c1.metric("News spikes found", len(results), border=True)
    c2.metric("Brent a week later: average", f"{week.mean():+.1f}%", border=True)
    c3.metric("Brent rose afterwards", f"{(week > 0).mean():.0%}", border=True)
    ui.event_paths(results, paths, "#2a78d6", SPIKE_TABLE, key="news_search_paths")
