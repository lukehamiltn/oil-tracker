"""
News analysis for the natural gas page, the gas version of the oil site's
news tools (news_page.py):

  Like this before  pick one of today's gas headlines (or type one): the past
                    stories worded most like it, and what Henry Hub did after
  Topics            one gas topic's worldwide coverage since 2015 with every
                    spike marked, Henry Hub after each spike, and all topics
                    compared
  Search            any theme in worldwide news (Media Cloud, about 1,600
                    sites since 2015, searched live): the days it suddenly
                    dominated the news, and what Henry Hub did next
  history_line      the "Last time: ..." line under each gas headline

Past stories come from the market news archive (Benzinga, since 2015) plus
the saved publisher articles, keeping those about natural gas.

Moves are shown as the TYPICAL (median) move, not the average: the daily
Henry Hub spot price has rare huge spikes on very cold days (+380% in a week
in January 2024), and one of those would swamp an average of ten stories.
"""

import html
import re
from urllib.parse import quote

import pandas as pd
import streamlit as st

import event_study as es
import market_news as mn
import markets as mk
import news
import news_page
import ui

MARKET = "NATGAS"
NAME = "Henry Hub"
MIN_PAST = 4                  # fewer close matches than this: no "Last time" line
# ("gas prices" alone usually means petrol at the pump, so it isn't matched)
GAS_TERMS = re.compile(r"natural gas|\bnat ?gas\b|\blng\b|henry hub|gas (?:storage|field|pipeline|export|supplies)"
                       r"|gazprom|nord stream|\bttf\b|liquefied", re.I)
TOPIC_KEYS = list(news.GAS_TOPICS)
LABELS = {k: t["label"] for k, t in news.GAS_TOPICS.items()}
COLORS = {k: t["color"] for k, t in news.GAS_TOPICS.items()}
EXAMPLES = ['"Freeport LNG"', '"Nord Stream"', '"polar vortex"', '"Sabine Pass"', "Gazprom",
            '"Henry Hub"', '"natural gas" "data center"', '"Waha"', '"Qatar" LNG', '"gas storage"']
VIEWS = {"now": "Today", "like": "Like this before", "topics": "Topics", "search": "Search"}


def is_gas(t: pd.DataFrame) -> pd.Series:
    return (t["headline"].fillna("") + " " + t["summary"].fillna("")).str.contains(GAS_TERMS)


def gas_related(t: pd.DataFrame) -> pd.DataFrame:
    return t[is_gas(t)]


def gas_pool(archive: pd.DataFrame) -> pd.DataFrame:
    """Every saved story about natural gas: the market news archive plus the
    publisher articles, with a 'day' (New York date) column."""
    articles = news_page.feed_archive()
    if not articles.empty:
        articles = articles.assign(
            day=articles["time"].dt.tz_convert(mn.MARKET_TZ).dt.tz_localize(None).dt.normalize())
    both = pd.concat([archive, articles], ignore_index=True).drop_duplicates("headline")
    both["summary"] = both["summary"].fillna("")
    # (the searchable text; publisher articles don't come with it)
    both["text"] = both["text"].fillna((both["headline"].fillna("") + " " + both["summary"]).str.lower())
    return gas_related(both)


def _version(archive: pd.DataFrame) -> str:
    return f"{len(archive)}-{archive['time'].max()}-{len(news_page.feed_archive())}"


@st.cache_resource(show_spinner="Indexing past gas headlines...", max_entries=1)
def matcher(_archive: pd.DataFrame, version: str):
    """Built once per archive version, from the gas stories only."""
    return mn.build_matcher(gas_pool(_archive), related=lambda t: t)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False, max_entries=300)
def past_matches(text: str, before: pd.Timestamp, _archive: pd.DataFrame, _prices: pd.Series,
                 version: str) -> tuple[pd.DataFrame, dict]:
    """(results, paths) of Henry Hub after the past gas stories most like `text`."""
    found = mn.similar(matcher(_archive, version), text, before)
    if found.empty:
        return pd.DataFrame(), {}
    found = found.assign(date=found["day"], description=found["headline"])
    return es.compute_results(_prices, found)


def history_line(h, prices: pd.Series, archive: pd.DataFrame, sig: mk.Significance) -> str:
    """'Last time: 6 similar stories -> Henry Hub +2.1% a week later (could be
    noise) - See them'. Empty without enough close matches."""
    if archive.empty:
        return ""
    before = (pd.Timestamp(h["time"]) - pd.Timedelta(days=14)).floor("h")
    results, _ = past_matches(str(h["headline"]), before, archive, prices, _version(archive))
    week = results["day_5_pct"].dropna() if not results.empty else pd.Series(dtype=float)
    if len(week) < MIN_PAST:
        return ""
    verdict = sig.check(MARKET, 5, week)
    text, color = mk.VERDICTS[verdict]
    tone = "#1d1d1b" if verdict in ("strong", "possible") else ui.MUTED
    link = "?like=" + quote(str(h["headline"])[:300])
    return (f'<div class="history">Last time: {len(week)} similar stories → {NAME} typically '
            f'<b style="color:{tone}">{week.median():+.1f}%</b> a week later · '
            f'<span style="color:{color}">{text.lower()}</span> · '
            f'<a href="{link}" target="_self">See them →</a></div>')


# Like this before -----------------------------------------------------------------
@st.fragment
def like_this_before(prices: pd.Series, sig: mk.Significance, heads: pd.DataFrame,
                     archive: pd.DataFrame) -> None:
    st.subheader("Has this happened before?", anchor=False)
    if archive.empty:
        st.info("The news archive isn't available right now. Please try again later.")
        return
    st.caption("Pick one of today's gas headlines, or type your own. We find the past gas stories "
               f"worded most like it, and show what {NAME} did after each one.")
    options = heads["headline"].tolist() if not heads.empty else []
    # Headlines that have close past matches first (others would show nothing)
    if options:
        found = {}
        for _, h in heads.head(30).iterrows():
            before = (pd.Timestamp(h["time"]) - pd.Timedelta(days=14)).floor("h")
            r, _ = past_matches(str(h["headline"]), before, archive, prices, _version(archive))
            found[h["headline"]] = len(r)
        options = sorted(options, key=lambda h: found.get(h, 0) < MIN_PAST)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Today's gas headlines**")
        if options:
            with st.container(height=340, key="gas_like_list"):
                meta = {h["headline"]: f"{h['source']} · {news_page._ago(h['time'])}" for _, h in heads.iterrows()}
                picked = st.radio("Today's headline", options, index=0, key="gas_like_pick",
                                  format_func=lambda h: f"{news_page._plain(h)}  \n:gray[{news_page._plain(meta.get(h, ''))}]",
                                  label_visibility="collapsed")
        else:
            picked = None
            st.caption("No gas headlines right now.")
    with c2:
        st.markdown("**Or type a headline**")
        typed = st.text_input("Or type a headline", key="gas_like_typed",
                              placeholder="e.g. Freeport LNG plant shut after fire",
                              label_visibility="collapsed")
        st.caption("Typing here overrides the picked headline. Clear it to go back to the list.")
    text = typed.strip() or picked
    if not text:
        return
    before = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)
    if not typed.strip() and not heads.empty:
        row = heads[heads["headline"] == picked]
        if len(row):
            before = row["time"].iloc[0] - pd.Timedelta(days=14)
    results, paths = past_matches(text, before.floor("h"), archive, prices, _version(archive))
    if results.empty:
        st.info("No past gas stories are worded closely enough to compare. Try a more specific "
                "headline (names of places, companies or events help most).")
        return
    day, week, month = results["day_1_pct"], results["day_5_pct"], results["day_20_pct"]
    verdict = lambda h, v: mk.VERDICTS[sig.check(MARKET, h, v)][0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Similar past stories", len(results), border=True)
    m2.metric(f"{NAME} next day: typical", f"{day.median():+.1f}%", verdict(1, day),
              delta_color="off", delta_arrow="off", border=True)
    m3.metric(f"{NAME} a week later: typical", f"{week.median():+.1f}%",
              f"{verdict(5, week)} · rose {(week > 0).mean():.0%}", delta_color="off", delta_arrow="off", border=True)
    m4.metric(f"{NAME} a month later: typical", f"{month.median():+.1f}%",
              f"{verdict(20, month)} · rose {(month > 0).mean():.0%}", delta_color="off", delta_arrow="off",
              border=True)
    ui.event_paths(results, paths, "#0f766e", news_page.MATCH_TABLE, key="gas_like_paths", market=NAME,
                   center="median")
    ui.tip("Similarity is based on shared wording (rare words like place and company names count most), "
           "so check the headlines to judge how alike the stories really are. With a handful of matches, "
           "one big move can swing the average, and gas moves a lot. That's why the numbers above are the "
           "typical (median) move: half the stories were followed by more, half by less.",
           "How matches are found")


# Topics ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def spikes_with_headlines(_spikes: pd.DataFrame, _archive: pd.DataFrame, version: str) -> pd.DataFrame:
    """The gas news spikes, each with a gas headline from around that day."""
    pool = gas_pool(_archive)

    def match(window, spike):
        words = re.sub(r"\((?!\?)", "(?:", news.GAS_TOPICS[spike["topic"]]["keywords"])
        return window["headline"].fillna("").str.contains(words, case=False, regex=True)
    return mn.add_headlines(_spikes, pool, match)


@st.fragment
def topics_view(prices: pd.Series, data: dict, archive: pd.DataFrame) -> None:
    st.subheader("One topic over time", anchor=False)
    timelines = data["timelines"]
    if timelines.empty:
        st.info("Gas news coverage is still being collected.")
        return
    topic = ui.topic_picker("Change topic", TOPIC_KEYS, LABELS, COLORS, key="gas_news_topic",
                            default=TOPIC_KEYS[0])
    results, paths = data["spike_react"]
    if not results.empty and not archive.empty:
        with_heads = spikes_with_headlines(data["spikes"], archive, _version(archive))
        results = results.merge(with_heads[["date", "topic", "headline"]], on=["date", "topic"], how="left")
        results["description"] = [f"{h}<br>{d}" if isinstance(h, str) and h else d
                                  for h, d in zip(results["headline"], results["description"])]
    t = timelines[timelines["topic"] == topic]
    spikes = results[results["topic"] == topic] if not results.empty else results
    ui.tip(f"`{news.GAS_TOPICS[topic]['query']}`", "Search used for worldwide news")
    news_page.coverage_chart(t, spikes, COLORS[topic], key="gas_news_cov", source="world")
    st.markdown(f"**{NAME} after each of the {len(spikes)} news spikes**")
    ui.event_paths(spikes, paths, COLORS[topic], news_page.SPIKE_TABLE, key="gas_topic_paths", market=NAME,
                   center="median")
    if not results.empty:
        st.divider()
        st.subheader("All topics compared", anchor=False)
        available = [k for k in TOPIC_KEYS if k in set(results["topic"])]
        ui.comparison_section(prices, results, paths, "topic", available, LABELS, COLORS, key="gas_news_cmp",
                              market=NAME, sig=data["sig"], market_key=MARKET, center="median")
        ui.tip("Based on news spikes in worldwide news coverage (Media Cloud): days when a topic got at least "
               f"{news.SPIKE_RATIO:.0f}× its normal share of all news.", "Source")


# Search ---------------------------------------------------------------------------
@st.cache_data(ttl=24 * 60 * 60, show_spinner=False, max_entries=200)
def worldwide_counts(query: str) -> pd.DataFrame:
    """Daily counts since 2015 for a search in worldwide news (Media Cloud).
    Remembered for a day, so each search is asked for once. Raises if Media
    Cloud can't be reached (no key, busy)."""
    import datetime as dt
    import mediacloud.api as mc
    import mediacloud_news
    key = mediacloud_news.api_key()
    if not key:
        raise RuntimeError("no Media Cloud key")
    t = mediacloud_news.counts(mc.SearchApi(key), query, mediacloud_news.HISTORY_START,
                               dt.datetime.now(dt.timezone.utc).date(), tries=1)
    return t.assign(topic="search")


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False, max_entries=200)
def archive_counts(query: str, _archive: pd.DataFrame, version: str) -> pd.DataFrame:
    """The backup: daily counts in the saved market news archive."""
    return mn.counts(_archive, mn.search_mask(_archive, query), "search")


@st.fragment
def search_view(prices: pd.Series, sig: mk.Significance, archive: pd.DataFrame) -> None:
    st.subheader("Search the news", anchor=False)
    st.caption("Searches worldwide news (about 1,600 English-language sites, since 2015) for any theme. "
               f"We find the days it suddenly dominated the news and show what {NAME} did next. Put exact "
               'phrases in quotes; use OR for alternatives, e.g. `"Freeport LNG" OR "Sabine Pass"`.')
    pick = st.pills("Try one", EXAMPLES, key="gas_news_example")
    with st.form("gas_news_search", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        typed = c1.text_input("News theme", placeholder='"LNG export"')
        submitted = c2.form_submit_button("Search history", width="stretch", type="primary")
    query = typed.strip() if submitted and typed.strip() else pick
    if not query:
        return
    source = "world"
    try:
        with st.spinner("Searching worldwide news (takes a few seconds)..."):
            t = worldwide_counts(query)
    except Exception as error:
        print(f"Media Cloud search unavailable: {error!r}")
        if archive.empty:
            st.info("Search isn't available right now. Please try again in a minute.")
            return
        st.caption("Worldwide news search is busy right now, so this searches our saved energy-market news "
                   "instead (far fewer stories). Try again in a minute for the full search.")
        t, source = archive_counts(query, archive, _version(archive)).assign(topic="search"), "market"
    total = int(t["articles"].sum())
    if not total:
        st.info(f"No stories found for {query}. Try fewer or simpler words.")
        return
    spikes = news.find_spikes(t, source=source, min_articles=None if source == "world" else 3)
    results, paths = es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {})
    st.markdown(f"**{total:,} stories mention {html.escape(query)}**")
    shown = results if not results.empty else pd.DataFrame(columns=["spike_day", "description"])
    news_page.coverage_chart(t, shown, "#0f766e", key="gas_search_cov", source=source)
    if results.empty:
        st.info("This theme never spiked sharply enough to count as a news event "
                f"(needs {news.SPIKE_RATIO:.0f}× its normal coverage on a busy day).")
    else:
        week = results["day_5_pct"]
        c1, c2, c3 = st.columns(3)
        c1.metric("News spikes found", len(results), border=True)
        c2.metric(f"{NAME} a week later: typical", f"{week.median():+.1f}%",
                  mk.VERDICTS[sig.check(MARKET, 5, week)][0], delta_color="off", delta_arrow="off", border=True)
        c3.metric(f"{NAME} rose afterwards", f"{(week > 0).mean():.0%}", border=True)
        ui.event_paths(results, paths, "#0f766e", news_page.SPIKE_TABLE, key="gas_search_paths", market=NAME,
                       center="median")
    if not archive.empty:
        pool = gas_pool(archive)
        recent = pool[mn.search_mask(pool, query)].sort_values("time", ascending=False).head(8)
        if len(recent):
            with st.expander("Most recent matching gas stories we've saved"):
                news_page.headline_list(recent.assign(topics=[[] for _ in range(len(recent))]))


# Topic stories (opened from a topic card) ---------------------------------------
@st.dialog("Latest stories", width="large")
def topic_dialog(topic: str, row, heads: pd.DataFrame, archive: pd.DataFrame, show_rows) -> None:
    """The recent gas stories about one topic, from our publishers and the archive."""
    label, color, _ = news_page.status(row["heat"], row["enough"], row["big_enough"])
    st.markdown(ui.status_line(label, color) + f"<div class='dialog-topic'>{LABELS[topic]}</div>",
                unsafe_allow_html=True)
    st.caption(f"{row['heat']:.1f}× normal coverage over the last 3 days: {row['articles_3d']:,} articles "
               "in worldwide news.")
    pool = pd.concat([heads, gas_pool(archive)], ignore_index=True).drop_duplicates("headline")
    pool = pool[pool["time"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)]
    words = re.sub(r"\((?!\?)", "(?:", news.GAS_TOPICS[topic]["keywords"])
    about = pool[pool["headline"].fillna("").str.contains(words, case=False, regex=True)]
    if about.empty:
        st.caption("None of our sources had a headline about this in the last two weeks. The worldwide "
                   "count includes articles that only mention it in passing.")
    else:
        st.markdown("**Latest stories, last 2 weeks**")
        about = about.assign(topics=about["headline"].map(lambda h: news.classify_gas(str(h))))
        show_rows(about.sort_values("time", ascending=False).head(12))

    def to_topic() -> None:
        st.session_state.update(gas_news_view="topics", gas_news_topic=topic)
    if st.button("See this topic over time, and what gas did after past spikes →", type="tertiary",
                 on_click=to_topic, key="gas_dialog_to_topic"):
        st.rerun()


def pick_view() -> str:
    """The row of buttons at the top of the News tab. A 'See them ->' link
    under a headline opens that story in Like this before."""
    st.session_state.setdefault("gas_news_view", "now")
    asked = st.query_params.get("like")
    if asked:
        st.session_state["gas_news_view"] = "like"
        st.session_state["gas_like_typed"] = asked
        del st.query_params["like"]
    view = st.segmented_control("Section", list(VIEWS), key="gas_news_view", format_func=VIEWS.get,
                                label_visibility="collapsed") or "now"
    st.write("")
    return view

