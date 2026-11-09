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
import markets as mk
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
def search_archive(query: str, _archive: pd.DataFrame, _markets: dict):
    """Search the saved market news archive: instant, no outside requests.
    Returns (daily counts, {market: (results, paths)}, most recent stories)."""
    match = mn.search_mask(_archive, query)
    t = mn.counts(_archive, match, "search")
    spikes = news.find_spikes(t, source="market", min_articles=3)
    spikes = mn.add_headlines(spikes, _archive,
                              lambda window, spike: mn.search_mask(window, query))
    recent = _archive[match].sort_values("time", ascending=False).head(8)
    return t, mk.reactions(_markets, spikes), recent


def status(heat: float) -> tuple[str, str, str]:
    """Label, colour and card background tint."""
    if heat >= news.SPIKE_RATIO:
        return "Spiking", "#e34948", "#fdf3f2"
    if heat >= 1.5:
        return "Elevated", "#d48f00", "#fdf8ec"
    return "Normal", "#1baf7a", "#f5fbf8"


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
        card_css = []
        for i, (_, row) in enumerate(heat.iterrows()):
            if i % 4 == 0:        # a fresh row of columns, so cards in a row match heights
                cols = st.columns(4)
            past = results[results["topic"] == row["topic"]]
            label, color, tint = status(row["heat"])
            key = f"heat_card_{row['topic']}"
            # every card: a top edge and faint background in its status colour
            card_css.append(f".st-key-{key} {{ background: {tint}; "
                            f"box-shadow: inset 0 4px 0 {color}; }}")
            with cols[i % 4].container(border=True, height="stretch", key=key):
                # Now: how loud is this story?
                number_color = "#1d1d1b" if label == "Normal" else color
                st.markdown(
                    ui.status_line(label, color, pulse=label == "Spiking")
                    + f"<div class='card-title'>{row['label']}</div>"
                    + f"<span class='heat-num' style='color:{number_color}'>{row['heat']:.1f}×</span>"
                    + " <span class='heat-unit'>normal coverage</span>"
                    + ui.heat_gauge(row["heat"], color),
                    unsafe_allow_html=True)
                # History: what happened after past spikes, and is it real?
                if len(past):
                    week = past["day_5_pct"]
                    verdict = data["sig"].check("BRENT", 5, week)
                    shade = ui.MUTED if verdict in ("noise", "few") else "#1d1d1b"
                    st.markdown(
                        "<div class='card-rule'></div>"
                        f"<div class='eyebrow' style='margin-top:0.4rem'>After {len(past)} past spikes</div>"
                        f"<div class='past'>Brent <b style='color:{shade}'>{week.mean():+.1f}%</b> "
                        f"the next week · rose {(week > 0).mean():.0%} of the time</div>"
                        + ui.verdict_badge(verdict),
                        unsafe_allow_html=True)
                else:
                    st.caption("No past spikes to compare with yet.")
        st.html(ui.CARD_CSS.replace("</style>", "\n".join(card_css) + "\n</style>"))
        st.write("")

    # ---- 2. Latest headlines ---------------------------------------------------
    ui.eyebrow("Latest headlines")
    st.subheader("Today's oil news", anchor=False)
    heads, is_live = latest_headlines(archive) if not archive.empty else (pd.DataFrame(), False)
    if not heads.empty:
        heads = heads.assign(tagged=heads["topics"].str.len() > 0).sort_values(
            ["tagged", "time"], ascending=[False, False])
    headlines_section(heads, is_live, archive)

    # ---- 3. Like this before -------------------------------------------------------
    if not archive.empty:
        st.write("")
        ui.eyebrow("Like this before")
        st.subheader("Has a story like this happened before?", anchor=False)
        like_this_before(data, archive, heads.head(15))

    # ---- 4. Explore a topic -----------------------------------------------------
    st.write("")
    ui.eyebrow("Explore a topic")
    st.subheader("Past news spikes and how oil reacted", anchor=False)
    explore_topic(prices, data)

    # ---- 4. Compare all topics ------------------------------------------------
    news_results, news_paths = data["news"]
    if not news_results.empty:
        st.write("")
        ui.eyebrow("All topics")
        st.subheader("Average market move after a news spike, by topic", anchor=False)
        all_topics(data, [k for k in TOPIC_KEYS if k in set(news_results["topic"])])

    # ---- 5. Search the archive ---------------------------------------------------
    st.write("")
    ui.eyebrow("Search the past")
    st.subheader("Look up any news theme", anchor=False)
    search_section(data, archive)


@st.fragment
def headlines_section(heads: pd.DataFrame, is_live: bool, archive: pd.DataFrame) -> None:
    """Today's headlines, or - when a topic is picked - the latest stories of
    that kind, going back through the archive if today was quiet."""
    topic = ui.topic_picker("Filter by topic", TOPIC_KEYS, LABELS, COLORS, key="headline_topic",
                            none_text="Showing all of today's news",
                            clear_text="Remove this filter")
    if topic:
        pool = pd.concat([heads, mn.oil_related(archive)], ignore_index=True)
        pool = pool.drop_duplicates("headline")
        shown = pool[pool["topics"].map(lambda ts: topic in ts)].sort_values(
            "time", ascending=False).head(15)
        if shown.empty:
            st.info(f"No stories about {LABELS[topic].lower()} yet.")
            return
        st.caption(f"The latest {len(shown)} stories tagged *{LABELS[topic]}*, newest "
                   f"first, going back to {shown['time'].min():%b %d, %Y}.")
        headline_list(shown)
    elif not heads.empty:
        if not is_live:
            st.caption(f"The live feed didn't respond, so these are the newest saved "
                       f"headlines (to {heads['time'].max():%b %d, %H:%M} UTC).")
        headline_list(heads.head(15))
    else:
        st.info("Headlines are temporarily unavailable; the rest of the page works as normal.")
        return
    st.caption("Market news from Benzinga via Alpaca. Tags are assigned by keyword, so a "
               "few stories may be tagged imperfectly. Click a headline to read the article.")


MATCH_TABLE = {
    "day": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
    "headline": st.column_config.TextColumn("Past headline", width="large"),
    "score": st.column_config.ProgressColumn("Similarity", format="%.2f", min_value=0,
                                             max_value=1),
    **ui.HORIZON_COLUMNS,
    "url": st.column_config.LinkColumn("Article", display_text="Open"),
}


@st.cache_resource(show_spinner="Indexing past headlines...", max_entries=1)
def matcher(_archive: pd.DataFrame, version: str):
    """Built once per archive version (it changes when new news is saved);
    only the newest version is kept in memory."""
    return mn.build_matcher(_archive)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False, max_entries=300)
def past_matches(text: str, before: pd.Timestamp, _archive: pd.DataFrame,
                 _markets: dict, version: str) -> dict:
    """{market: (results, paths)} for the past stories most like `text`."""
    found = mn.similar(matcher(_archive, version), text, before)
    if found.empty:
        return {}
    found = found.assign(date=found["day"], description=found["headline"])
    return mk.reactions(_markets, found)


@st.fragment
def like_this_before(data, archive, heads) -> None:
    st.caption("Pick one of today's headlines, or type your own. We find the past stories "
               "worded most like it, and show what Brent did after each one.")
    options = heads["headline"].tolist() if not heads.empty else []
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    picked = c1.selectbox("Today's headline", options, index=0 if options else None,
                          placeholder="No headlines right now", key="like_pick")
    typed = c2.text_input("Or type a headline", key="like_typed",
                          placeholder="e.g. Drone attack hits Saudi oil facility")
    text = typed.strip() or picked
    if not text:
        return
    # Only stories from at least two weeks before this one. Rounded to the
    # hour so repeat searches reuse the saved answer.
    before = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)
    if not typed.strip() and not heads.empty:
        row = heads[heads["headline"] == picked]
        if len(row):
            before = row["time"].iloc[0] - pd.Timedelta(days=14)
    before = before.floor("h")
    version = f"{len(archive)}-{archive['time'].max()}"
    by_market = past_matches(text, before, archive, data["markets"], version)
    results, paths = by_market.get("BRENT", (pd.DataFrame(), {}))
    if results.empty:
        st.info("No past stories are worded closely enough to compare. Try a more "
                "specific headline (names of places, companies or events help most).")
        return
    day, week, month = results["day_1_pct"], results["day_5_pct"], results["day_20_pct"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Similar past stories", len(results), border=True)
    verdict = lambda h, v: mk.VERDICTS[data["sig"].check("BRENT", h, v)][0]
    m2.metric("Brent next day: average", f"{day.mean():+.1f}%", verdict(1, day),
              delta_color="off", delta_arrow="off", border=True)
    m3.metric("Brent a week later: average", f"{week.mean():+.1f}%",
              f"{verdict(5, week)} · rose {(week > 0).mean():.0%}", delta_color="off",
              delta_arrow="off", border=True)
    m4.metric("Brent a month later: average", f"{month.mean():+.1f}%",
              f"{verdict(20, month)} · rose {(month > 0).mean():.0%}", delta_color="off",
              delta_arrow="off", border=True)
    ui.event_paths(results, paths, "#2a78d6", MATCH_TABLE, key="like_paths")
    st.markdown("**How every market moved after these stories**")
    ui.market_reaction_table(by_market, data["typical"], key="like", sig=data["sig"])
    st.caption("Similarity is based on shared wording (rare words like place and company "
               "names count most), so check the headlines to judge how alike the stories "
               "really are. With about 10 matches, one big move can swing the average.")


@st.fragment
def all_topics(data, available) -> None:
    """Average move after a news spike, by topic, in any market."""
    market = ui.market_picker("news_cmp_market", data["markets"])
    results, paths = data["react"]["news"][market]
    ui.comparison_section(data["markets"][market], results, paths, "topic", available,
                          LABELS, COLORS, key="news_cmp", market=mk.MARKETS[market][1],
                          sig=data["sig"], market_key=market)
    st.markdown("**The same news spikes in every market**")
    ui.cross_market_section(data["react"]["news"], data["typical"], "topic", available,
                            LABELS, key="news_cmp", sig=data["sig"])
    st.caption("Based on worldwide news spikes (GDELT).")


@st.fragment
def explore_topic(prices, data) -> None:
    topic = ui.topic_picker("Change topic", TOPIC_KEYS, LABELS, COLORS, key="news_topic",
                            default=TOPIC_KEYS[0])
    source = st.segmented_control("News source", list(SOURCE_NAMES), default="gdelt",
                                  format_func=lambda k: SOURCE_NAMES[k],
                                  key="news_source") or "gdelt"
    timelines = data["timelines"] if source == "gdelt" else data["market_timelines"]
    by_market = data["react"]["news" if source == "gdelt" else "market_news"]
    market = ui.market_picker("news_topic_market", data["markets"])
    name = mk.MARKETS[market][1]
    results, paths = by_market[market]
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
    st.markdown(f"**{name} after each of the {len(spikes)} news spikes**")
    ui.event_paths(spikes, paths, COLORS[topic], SPIKE_TABLE, key="news_topic_paths",
                   market=name)
    st.markdown("**How every market moved after these spikes**")
    ui.market_reaction_table(by_market, data["typical"], key="news_topic",
                             keep=lambda r: r["topic"] == topic, sig=data["sig"])


@st.fragment
def search_section(data, archive) -> None:
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
    t, by_market, recent = search_archive(query, archive, data["markets"])
    results, paths = by_market.get("BRENT", (pd.DataFrame(), {}))
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
        c2.metric("Brent a week later: average", f"{week.mean():+.1f}%",
                  mk.VERDICTS[data["sig"].check("BRENT", 5, week)][0], delta_color="off",
                  delta_arrow="off", border=True)
        c3.metric("Brent rose afterwards", f"{(week > 0).mean():.0%}", border=True)
        ui.event_paths(results, paths, "#2a78d6", SPIKE_TABLE, key="news_search_paths")
        st.markdown("**How every market moved after these spikes**")
        ui.market_reaction_table(by_market, data["typical"], key="news_search",
                                 sig=data["sig"])
    with st.expander("Most recent matching stories"):
        headline_list(recent)
