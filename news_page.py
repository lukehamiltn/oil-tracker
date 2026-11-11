"""
The News page: today's oil news -> similar moments in the past -> what the
oil market did next.

News sources:
  - Articles from about 30 publishers' public news feeds (news_feeds.py): the
    "Latest headlines" list, each linking to the full article.
  - Benzinga's newswire (market_news.py): one-line flashes, shown separately
    with links to matching coverage; and the archive since 2015 used for
    "Like this before" and search.
  - Worldwide news coverage counts (Media Cloud, since 2015): the topic cards.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import flash_sources
import market_news as mn
import markets as mk
import news
import news_feeds as nf
import ui

TOPIC_KEYS = list(news.TOPICS)
LABELS = {k: t["label"] for k, t in news.TOPICS.items()}
COLORS = {k: t["color"] for k, t in news.TOPICS.items()}
SOURCE_NAMES = {"world": "Worldwide news (Media Cloud, since 2015)",
                "market": "Market news (Benzinga, since 2015)"}
EXAMPLES = ['"Strait of Hormuz"', "Houthi", "refinery fire", "Abqaiq", "Libya",
            '"price war"', '"rig count"', "hurricane", "Venezuela", "lockdown"]

SPIKE_TABLE = {
    "spike_day": st.column_config.DateColumn("News spike", format="YYYY-MM-DD"),
    "headline": st.column_config.TextColumn("Headline around then", width="large"),
    "ratio": st.column_config.NumberColumn("Coverage vs normal", format="%.1fx"),
    "articles": st.column_config.NumberColumn("Articles", format="%d"),
    **ui.HORIZON_COLUMNS,
}


def current_heat(data: dict) -> tuple[pd.DataFrame, str]:
    """Topic heat from worldwide news, or from market news if the worldwide
    data is more than a few days old (e.g. the update job failed)."""
    return news.heat_now(data["timelines"], data["market_timelines"])


@st.cache_data(ttl=60 * 60, show_spinner=False)
def feed_archive() -> pd.DataFrame:
    """Saved articles from the publishers' feeds (added to every 3 hours)."""
    return nf.load_archive()


@st.cache_resource(max_entries=1)
def _search_words(version: str) -> bool:
    """Teach the web-search helper which words are common (once per archive)."""
    flash_sources.prepare(mn.load_archive()["headline"])
    return True


def _display_source(source: str) -> str:
    return "Benzinga" if str(source).lower() == "benzinga" else str(source)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def latest_headlines(_archive: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """(today's news, live?). One table with a "kind" column:
      - "article": real articles from the publishers' feeds, plus Benzinga
        stories that have an article behind them
      - "flash": Benzinga's one-line newswire flashes, each with "coverage"
        (matching articles from the feeds, if any)
    Read live (every 15 minutes); if a source doesn't answer, the newest saved
    stories are used instead."""
    live = True
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=48)
    try:
        pool = nf.fetch(oil_only=False)          # everything, for matching flashes
    except Exception as error:
        print(f"News feeds unavailable: {error}")
        pool = pd.DataFrame(columns=nf.COLUMNS)
    if pool.empty:
        live = False
        saved = feed_archive()
        pool = saved[saved["time"] >= since] if not saved.empty else saved
    feed_text = pool["headline"] + " " + pool["summary"]
    articles = pool[feed_text.str.contains(nf.OIL_TERMS)] if len(pool) else pool
    try:
        wire = mn.latest()
    except Exception as error:
        print(f"Benzinga unavailable, using saved stories: {error}")
        wire = pd.DataFrame()
    if wire.empty:
        live = False
        recent = _archive[_archive["time"] >= _archive["time"].max() - pd.Timedelta(hours=48)]
        wire = mn.oil_related(recent)
    flash = wire["summary"].map(mn.is_flash)
    articles = pd.concat([articles, wire[~flash]], ignore_index=True)
    articles = (articles.sort_values("time", ascending=False)
                .drop_duplicates("headline").assign(kind="article"))
    flashes = wire[flash].sort_values("time", ascending=False)
    flashes = flashes.assign(kind="flash",
                             coverage=nf.match_coverage(flashes, pool, min_score=0.18))
    heads = pd.concat([articles, flashes], ignore_index=True)
    heads["source"] = heads["source"].map(_display_source)
    return heads, live


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


def status(heat: float, enough: bool = True) -> tuple[str, str, str]:
    """Label, colour and card background tint."""
    if not enough:            # too few articles to call it busy or quiet
        return "Quiet", "#898781", "#f7f7f5"
    if heat >= news.SPIKE_RATIO:
        return "Spiking", "#e34948", "#fdf3f2"
    if heat >= 1.5:
        return "Elevated", "#d48f00", "#fdf8ec"
    return "Normal", "#1baf7a", "#f5fbf8"


def coverage_chart(t: pd.DataFrame, spikes: pd.DataFrame, color: str, key: str,
                   source: str = "world") -> None:
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
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=key)


def _ago(time: pd.Timestamp) -> str:
    hours = max(int((pd.Timestamp.now(tz="UTC") - time).total_seconds() // 3600), 0)
    if hours < 1:
        return "just now"
    return f"{hours}h ago" if hours < 48 else f"{time:%b %d, %Y}"


def _link(label: str, url: str, cls: str = "more") -> str:
    return (f'<a class="{cls}" href="{html.escape(url)}" target="_blank" '
            f'rel="noopener">{html.escape(label)} ↗</a>')


def headline_list(heads: pd.DataFrame) -> None:
    """Articles: headline (links to the article), summary, publisher and time.
    Newswire flashes have no article, so they show the full headline with
    links to matching coverage, the source they cite, or a short web search."""
    _search_words(str(len(mn.load_archive())))
    rows = []
    for _, h in heads.iterrows():
        chips = "".join(ui.chip(LABELS[t], COLORS[t]) for t in h["topics"])
        title = html.escape(h["headline"])
        source = f'<span class="publisher">{html.escape(_display_source(h["source"]))}</span>'
        # Only Benzinga's one-liners are flashes (a publisher's article with no
        # summary is still an article)
        is_flash = (h["kind"] == "flash" if "kind" in h and isinstance(h["kind"], str)
                    else mn.is_flash(h.get("summary")))
        if is_flash:
            coverage = h.get("coverage") if isinstance(h.get("coverage"), list) else []
            links = [_link(c["source"], c["url"]) for c in coverage]
            if not links:
                links = [_link(label, url) for label, url
                         in flash_sources.links(h["headline"], h["time"])]
            label = "Coverage" if coverage else "Read more"
            rows.append(f'<div class="headline flash-row"><span class="flash-title">{title}</span>'
                        f'<div class="meta">{chips}{source} newswire · {_ago(h["time"])}'
                        f' · <span class="flash">{label}:</span> {" · ".join(links)}</div></div>')
        else:
            summary = (f'<div class="summary">{html.escape(h["summary"])}</div>'
                       if isinstance(h["summary"], str) and h["summary"] else "")
            rows.append(f'<div class="headline"><a href="{html.escape(h["url"])}" target="_blank" '
                        f'rel="noopener">{title}</a>{summary}<div class="meta">{chips}'
                        f'{source} · {_ago(h["time"])}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


def _spread(articles: pd.DataFrame, per_source: int = 3, n: int = 20) -> pd.DataFrame:
    """Newest first, but at most a few stories per publisher, so one site
    posting a batch can't fill the list."""
    articles = articles.sort_values("time", ascending=False)
    return articles[articles.groupby("source").cumcount() < per_source].head(n)


VIEWS = {
    "now": "Today",
    "like": "Like this before",
    "topics": "Topics",
    "search": "Search",
}


@st.fragment
def render(prices: pd.Series, data: dict) -> None:
    """The News tab, split into four views picked from a row of buttons, so
    each fits on a screen or two (a fragment: switching only redraws this tab)."""
    st.session_state.setdefault("news_view", "now")    # (the jump button can change it)
    view = st.segmented_control("Section", list(VIEWS), key="news_view",
                                format_func=VIEWS.get, label_visibility="collapsed") or "now"
    st.write("")
    archive = data["archive"]
    if view == "now":
        now_view(data)
    elif view == "like":
        if archive.empty:
            st.info("The news archive isn't available right now. Please try again later.")
            return
        st.subheader("Has this happened before?", anchor=False)
        like_this_before(data, archive, todays_headlines(archive).head(15))
    elif view == "topics":
        st.subheader("One topic over time", anchor=False)
        explore_topic(prices, data)
        news_results = data["news"][0]
        if not news_results.empty:
            st.divider()
            st.subheader("All topics compared", anchor=False)
            all_topics(data, [k for k in TOPIC_KEYS if k in set(news_results["topic"])])
    else:
        st.subheader("Search the archive", anchor=False)
        search_section(data, archive)


def todays_headlines(archive: pd.DataFrame) -> pd.DataFrame:
    """Today's articles and flashes, topic-tagged stories first, then newest first."""
    heads, _ = latest_headlines(archive)
    if heads.empty:
        return heads
    return heads.assign(tagged=heads["topics"].str.len() > 0).sort_values(
        ["tagged", "time"], ascending=[False, False])


def now_view(data: dict) -> None:
    archive = data["archive"]
    heat, heat_source = current_heat(data)
    results = data["news"][0] if heat_source == "world" else data["market_news"][0]

    # ---- 1. What's in the news now ------------------------------------------
    if not heat.empty:
        st.subheader("What's in the news", anchor=False)
        st.caption(f"Coverage over the last 3 days compared with normal, from "
                   f"{SOURCE_NAMES[heat_source].split(' (')[0].lower()} (data to "
                   f"{heat['last_day'].max():%b %d, %Y}). For each topic: what Brent did "
                   "in the week after past news spikes.")
        card_css = []
        for i, (_, row) in enumerate(heat.iterrows()):
            if i % 4 == 0:        # a fresh row of columns, so cards in a row match heights
                cols = st.columns(4)
            past = results[results["topic"] == row["topic"]]
            label, color, tint = status(row["heat"], row["enough"])
            key = f"heat_card_{row['topic']}"
            # every card: a faint background in its status colour, plus a
            # coloured top edge that appears on hover
            card_css.append(f".st-key-{key} {{ background: {tint}; transition: box-shadow 0.15s; }} "
                            f".st-key-{key}:hover {{ box-shadow: inset 0 4px 0 {color}; }}")
            with cols[i % 4].container(border=True, height="stretch", key=key):
                # Now: how loud is this story?
                number_color = color if label in ("Spiking", "Elevated") else "#1d1d1b"
                st.markdown(
                    ui.status_line(label, color, pulse=label == "Spiking")
                    + f"<div class='card-title'>{row['label']}</div>"
                    + f"<span class='heat-num' style='color:{number_color}'>{row['heat']:.1f}×</span>"
                    + (" <span class='heat-unit'>normal coverage</span>" if row["enough"] else
                       f" <span class='heat-unit'>normal · only {row['articles_3d']} "
                       f"article{'s' if row['articles_3d'] != 1 else ''}</span>")
                    + ui.heat_gauge(row["heat"], color),
                    unsafe_allow_html=True)
                # History: what happened after past spikes, and is it real?
                if len(past):
                    week = past["day_5_pct"]
                    p = data["sig"].p_value("BRENT", 5, week)
                    verdict = data["sig"].verdict(p, week.notna().sum())
                    tip = ui.verdict_tip(verdict, p, int(week.notna().sum()), "week for Brent")
                    shade = ui.MUTED if verdict in ("noise", "few") else "#1d1d1b"
                    st.markdown(
                        "<div class='card-rule'></div>"
                        f"<div class='eyebrow' style='margin-top:0.4rem'>After {len(past)} past spikes</div>"
                        f"<div class='past'>Brent <b style='color:{shade}'>{week.mean():+.1f}%</b> "
                        f"the next week · rose {(week > 0).mean():.0%} of the time</div>"
                        + ui.verdict_badge(verdict, tip),
                        unsafe_allow_html=True)
                else:
                    st.caption("No past spikes to compare with yet.")
        st.html(ui.CARD_CSS.replace("</style>", "\n".join(card_css) + "\n</style>"))
        st.write("")

    # ---- 2. Latest headlines ---------------------------------------------------
    st.subheader("Latest headlines", anchor=False)
    heads, is_live = latest_headlines(archive)
    headlines_section(heads, is_live, archive)
    st.button("Has a story like one of these happened before? →", type="tertiary",
              key="to_like", on_click=lambda: st.session_state.update(news_view="like"))


@st.fragment
def headlines_section(heads: pd.DataFrame, is_live: bool, archive: pd.DataFrame) -> None:
    """Today's headlines, or - when a topic is picked - the latest stories of
    that kind, going back through the archive if today was quiet."""
    topic = ui.topic_picker("Filter by topic", TOPIC_KEYS, LABELS, COLORS, key="headline_topic",
                            none_text="Showing all of today's news",
                            clear_text="Remove this filter")
    if heads.empty:
        st.info("Headlines are temporarily unavailable; the rest of the page works as normal.")
        return
    articles = heads[heads["kind"] == "article"]
    flashes = heads[heads["kind"] == "flash"]
    if topic:
        saved = pd.concat([feed_archive(), mn.oil_related(archive)], ignore_index=True)
        saved = saved[~saved["summary"].map(mn.is_flash)]
        pool = pd.concat([articles, saved], ignore_index=True).drop_duplicates("headline")
        articles = pool[pool["topics"].map(lambda ts: topic in ts)]
        flashes = flashes[flashes["topics"].map(lambda ts: topic in ts)]
        if articles.empty and flashes.empty:
            st.info(f"No stories about {LABELS[topic].lower()} yet.")
            return
    if not is_live:
        st.caption("A news source didn't respond, so some of these are the newest saved "
                   "stories.")
    shown = _spread(articles, n=12 if topic else 20)
    if len(shown):
        if topic:
            st.caption(f"The latest stories tagged *{LABELS[topic]}*, newest first, going "
                       f"back to {shown['time'].min():%b %d, %Y}.")
        headline_list(shown)
        ui.tip(f"Articles from {articles['source'].nunique()} publishers' news feeds "
               "(energy press, shipping, world and Middle East news), newest first, at most "
               "three per publisher. Click a headline to read the full article on the "
               "publisher's site. Topic tags are assigned by keyword, so a few may be off.",
               "About these stories")
    if len(flashes):
        st.markdown("<div class='eyebrow' style='margin-top:1.2rem'>From the newswire</div>",
                    unsafe_allow_html=True)
        headline_list(flashes.head(10))
        ui.tip("Benzinga newswire flashes are one-line headlines with no article behind "
               "them. Where other outlets have covered the same story, we link to their "
               "articles; otherwise to the source the flash cites, or a short web search.",
               "About the newswire")


MATCH_TABLE = {
    "day": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
    "headline": st.column_config.TextColumn("Past headline", width="large"),
    "score": st.column_config.ProgressColumn("Similarity", format="%.2f", min_value=0,
                                             max_value=1),
    **ui.HORIZON_COLUMNS,
    "url": st.column_config.LinkColumn("Read", display_text="Open ↗",
                                       help="The article, or for one-line newswire flashes "
                                            "(no article), other outlets' coverage"),
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



def _plain(text: str) -> str:
    """Show text exactly as written (radio labels are read as Markdown, where
    $ * _ and friends would change the formatting)."""
    for ch in "\\`*_{}[]()#+-.!$~|<>":      # backslash first, so it isn't doubled
        text = text.replace(ch, "\\" + ch)
    return text


@st.fragment
def like_this_before(data, archive, heads) -> None:
    st.caption("Pick one of today's headlines, or type your own. We find the past stories "
               "worded most like it, and show what Brent did after each one.")
    options = heads["headline"].tolist() if not heads.empty else []
    # Round-up headlines ("Benzinga Market Summary: ...") only match other
    # round-ups, so put a specific story first
    options = sorted(options, key=lambda h: "market summary" in h.lower())
    c1, c2 = st.columns([3, 2])
    # A scrollable list rather than a dropdown, so every headline shows in full
    with c1:
        st.markdown("**Today's headlines**")
        if options:
            with st.container(height=340, key="like_list"):
                meta = {h["headline"]: f"{h['source']} · {_ago(h['time'])}"
                        for _, h in heads.iterrows()}
                picked = st.radio("Today's headline", options, index=0, key="like_pick",
                                  format_func=lambda h: f"{_plain(h)}  \n:gray[{_plain(meta.get(h, ''))}]",
                                  label_visibility="collapsed")
        else:
            picked = None
            st.caption("No headlines right now.")
    with c2:
        st.markdown("**Or type a headline**")
        typed = st.text_input("Or type a headline", key="like_typed",
                              placeholder="e.g. Drone attack hits Saudi oil facility",
                              label_visibility="collapsed")
        st.caption("Typing here overrides the picked headline. Clear it to go back to the list.")
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
    ui.tip("Similarity is based on shared wording (rare words like place and company "
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
    ui.tip("Based on news spikes in worldwide news coverage (Media Cloud).", "Source")


@st.fragment
def explore_topic(prices, data) -> None:
    topic = ui.topic_picker("Change topic", TOPIC_KEYS, LABELS, COLORS, key="news_topic",
                            default=TOPIC_KEYS[0])
    source = st.segmented_control("News source", list(SOURCE_NAMES), default="world",
                                  format_func=lambda k: SOURCE_NAMES[k],
                                  key="news_source") or "world"
    timelines = data["timelines"] if source == "world" else data["market_timelines"]
    by_market = data["react"]["news" if source == "world" else "market_news"]
    market = ui.market_picker("news_topic_market", data["markets"])
    name = mk.MARKETS[market][1]
    results, paths = by_market[market]
    t = timelines[timelines["topic"] == topic]
    if t.empty:
        st.info("No data for this topic from this source yet.")
        return
    spikes = results[results["topic"] == topic] if not results.empty else results
    if source == "world":
        ui.tip(f"`{news.TOPICS[topic]['query']}`", "Search used for worldwide news")
    else:
        ui.tip("Share of all saved oil-market news whose headline matches this topic.")
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
