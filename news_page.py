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
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import flash_sources
import market_news as mn
import markets as mk
import news
import news_feeds as nf
import live_prices
import recap
import ui
import upcoming

TOPIC_KEYS = list(news.TOPICS)
LABELS = {k: t["label"] for k, t in news.TOPICS.items()}
COLORS = {k: t["color"] for k, t in news.TOPICS.items()}
SOURCE_NAMES = {"world": "Worldwide news (Media Cloud, since 2015)",
                "market": "Market news (Benzinga, since 2015)"}
EXAMPLES = ['"Strait of Hormuz"', "Houthi", "refinery fire", "Abqaiq", "Libya",
            '"price war"', '"rig count"', "hurricane", "Venezuela", "lockdown"]

SPIKE_TABLE = {
    "spike_day": st.column_config.DateColumn("News spike", format="MMM D, YYYY"),
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


def status(heat: float, enough: bool = True, big_enough: bool = True) -> tuple[str, str, str]:
    """Label, colour and card background tint. A high ratio on few stories
    shows as Elevated, not Spiking (see news.SOURCES spike_articles)."""
    if not enough:            # too few articles to call it busy or quiet
        return "Quiet", "#898781", "#f7f7f5"
    if heat >= news.SPIKE_RATIO and big_enough:
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
                             hovertemplate="%{x|%b %-d, %Y}: " + unit + "<extra></extra>"))
    if not spikes.empty:
        at = smooth.reindex(spikes["spike_day"]).values
        fig.add_trace(go.Scatter(
            x=spikes["spike_day"], y=at, mode="markers", name="News spike",
            marker=dict(size=9, color="#ffffff", line=dict(color="#1d1d1b", width=2)),
            customdata=spikes[["description"]].values,
            hovertemplate="<b>%{x|%b %-d, %Y}</b><br>%{customdata[0]}<extra></extra>"))
    ui.base_layout(fig, 300, hovermode="closest", yaxis_title=title)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=key)


def _ago(time: pd.Timestamp) -> str:
    seconds = max((pd.Timestamp.now(tz="UTC") - time).total_seconds(), 0)
    if seconds < 3600:
        minutes = int(seconds // 60)
        return "just now" if minutes < 2 else f"{minutes} min ago"
    hours = int(seconds // 3600)
    return f"{hours}h ago" if hours < 48 else f"{ui.day(time)}"


def _link(label: str, url: str, cls: str = "more") -> str:
    return (f'<a class="{cls}" href="{html.escape(url)}" target="_blank" '
            f'rel="noopener">{html.escape(label)} ↗</a>')


MIN_PAST = 3      # past matches needed before a "Last time" line is shown


def history_line(h, data: dict) -> str:
    """'Last time: 8 similar stories -> Brent -1.4% a week later (could be noise)
    - See them', linking to this story in Like this before. Empty if there
    aren't enough close matches (better no line than a misleading one)."""
    archive = data["archive"]
    if archive.empty:
        return ""
    before = (pd.Timestamp(h["time"]) - pd.Timedelta(days=14)).floor("h")
    version = f"{len(archive)}-{archive['time'].max()}-{len(feed_archive())}"
    by_market = past_matches(h["headline"], before, archive, data["markets"], version)
    results = by_market.get("BRENT", (pd.DataFrame(), {}))[0]
    week = results["day_5_pct"].dropna() if not results.empty else pd.Series(dtype=float)
    if len(week) < MIN_PAST:
        return ""
    verdict = data["sig"].check("BRENT", 5, week)
    text, color = mk.VERDICTS[verdict]
    tone = "#1d1d1b" if verdict in ("strong", "possible") else ui.MUTED
    link = "?like=" + quote(h["headline"][:300])
    return (f'<div class="history">Last time: {len(week)} similar stories → Brent '
            f'<b style="color:{tone}">{week.mean():+.1f}%</b> a week later · '
            f'<span style="color:{color}">{text.lower()}</span> · '
            f'<a href="{link}" target="_self">See them →</a></div>')


def headline_list(heads: pd.DataFrame, data: dict | None = None) -> None:
    """Articles: headline (links to the article), summary, publisher and time.
    Newswire flashes have no article, so they show the full headline with
    links to matching coverage, the source they cite, or a short web search.
    With `data`, each story also gets a "Last time" line from past news."""
    _search_words(str(len(mn.load_archive())))
    rows = []
    for _, h in heads.iterrows():
        past = history_line(h, data) if data is not None else ""
        chips = "".join(ui.chip(LABELS[t], COLORS[t]) for t in h["topics"])
        title = html.escape(ui.headline_case(h["headline"]))
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
                        f' · <span class="flash">{label}:</span> {" · ".join(links)}</div>'
                        f'{past}</div>')
        else:
            summary = (f'<div class="summary">{html.escape(h["summary"])}</div>'
                       if isinstance(h["summary"], str) and h["summary"] else "")
            # (worldwide-news stories only have a date, and may be reprinted elsewhere)
            when = ui.day(h["time"], year=False) if h.get("date_only") == True else _ago(h["time"])
            copies = h.get("copies")
            reprints = (f' · also on {int(copies) - 1} other site{"s" if copies > 2 else ""}'
                        if pd.notna(copies) and copies > 1 else "")
            rows.append(f'<div class="headline"><a href="{html.escape(h["url"])}" target="_blank" '
                        f'rel="noopener">{title}</a>{summary}<div class="meta">{chips}'
                        f'{source} · {when}{reprints}</div>{past}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


SHOW_FIRST = 10     # headlines shown before "Show more"


def _spread(articles: pd.DataFrame, per_source: int = 3, n: int = 20) -> pd.DataFrame:
    """Newest first, but at most a few stories per publisher, so one site
    posting a batch can't fill the list."""
    articles = articles.sort_values("time", ascending=False)
    return articles[articles.groupby("source").cumcount() < per_source].head(n)


VIEWS = {
    "now": "Today",
    "like": "Like this before",
    "review": "Week in review",
    "topics": "Topics",
    "search": "Search",
}


@st.fragment
def render(prices: pd.Series, data: dict) -> None:
    """The News tab, split into four views picked from a row of buttons, so
    each fits on a screen or two (a fragment: switching only redraws this tab)."""
    st.session_state.setdefault("news_view", "now")    # (the jump button can change it)
    # A "See them ->" link under a headline opens that story in Like this before
    asked = st.query_params.get("like")
    if asked:
        st.session_state["news_view"] = "like"
        st.session_state["like_typed"] = asked
        del st.query_params["like"]
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
    elif view == "review":
        week_in_review(data)
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


@st.cache_data(ttl=30 * 60, show_spinner=False)
def _week_data(version: str, _prices: pd.Series):
    """Recent closes for every market, and Brent carried up to today."""
    extended, _ = live_prices.extend(_prices)
    return recap.market_closes(), extended


def week_in_review(data: dict) -> None:
    st.subheader("Week in review", anchor=False)
    st.caption("How oil and related markets moved, what made the news, and for each event "
               "what history suggested compared with what actually happened.")
    weeks = recap.weeks(8)
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    labels = {i: (f"{m:%b} {m.day}–{f:%b} {f.day}" + (" (this week)" if m <= today <= f + pd.Timedelta(days=2) and i == 0 else ""))
              for i, (m, f) in enumerate(weeks)}
    pick = st.selectbox("Week", list(labels), format_func=labels.get, key="review_week")
    monday, friday = weeks[pick]
    closes, prices = _week_data(f"{data['prices'].index[-1]}", data["prices"])
    unfinished = today <= friday

    # 1. How markets moved
    cards = []
    for m in recap.WEEK_MARKETS:
        move = recap.week_move(closes.get(m, pd.Series(dtype=float)), monday, friday)
        if move is None:
            continue
        color = "#1d8a5e" if move >= 0 else "#c43a39"
        cards.append((mk.MARKETS[m][0], f'<span style="color:{color}">{move:+.1f}%</span>',
                      "so far this week" if unfinished else "over the week", None))
    if cards:
        st.markdown("**How markets moved**")
        ui.kpi_row(cards, columns=4)
        ui.tip("Change from the last close before Monday to the latest close that week. Oil "
               "markets use front-month futures; energy stocks are the XLE fund; the dollar is "
               "the ICE U.S. dollar index.", "About these numbers")

    # 2. What made the news
    topics = recap.topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        st.markdown("**What made the news**")
        rows = "".join(
            f'<div class="headline"><span class="flash-title">{html.escape(r.label)}</span>'
            f'<div class="meta">{r.ratio:.1f}× its normal share of worldwide news · '
            f'{r.articles:,} stories</div></div>' for r in topics.head(3).itertuples())
        st.markdown(rows, unsafe_allow_html=True)

    # 3. Events that week, history vs what happened
    events = recap.scored(data, prices, recap.events_between(data, monday, friday))
    st.markdown("**What happened, and what history suggested**")
    if events.empty:
        st.caption("No news spikes or scheduled oil events that week.")
    else:
        table = pd.DataFrame({
            "Day": events["day"].map(lambda d: ui.day(d, year=False, weekday=True)),
            "Event": events["label"],
            "History said (Brent, next week)": [
                f"{e:+.1f}% avg after {n} past · {mk.VERDICTS[v][0].lower()}" if n else "no past events"
                for e, n, v in zip(events["expected"], events["n_past"], events["verdict"])],
            "What happened": [
                "—" if a is None else f"{a:+.1f}%" + ("" if d == recap.HORIZON else f" (after {d} days)")
                for a, d in zip(events["actual"], events["days"])],
            "Right way?": ["—" if r is None else ("Yes" if r else "No") for r in events["right_way"]],
        })
        st.dataframe(table, hide_index=True, width="stretch", key="review_table")
        ui.tip("'History said' is the average Brent move in the week after past events of the "
               "same type, using only events before this one. 'What happened' is Brent's move "
               "over the next 5 trading days from the close before the event. 'Right way?' "
               "compares just the direction, once the week is over.", "How to read this")

    # 4. Track record
    record = recap.track_record(data, prices)
    if len(record):
        hits, total = int(record["right_way"].sum()), len(record)
        st.markdown("**Track record**")
        ui.kpi_row([("History pointed the right way", f"{hits} of {total}",
                     f"{hits / total:.0%} of news spikes, OPEC+ and Fed decisions and big EIA "
                     "surprises in the last 6 months", None)], columns=1)
        st.caption("Close to a coin flip, which fits the site's 'could be noise' labels: the "
                   "averages here describe what usually happened, they are not forecasts.")


def coming_up(data: dict) -> None:
    """The next scheduled events that move oil, with what history says."""
    try:
        events = upcoming.upcoming()
    except Exception as error:
        print(f"Calendar unavailable: {error!r}")
        return
    if events.empty:
        return
    today = pd.Timestamp.now(tz=upcoming.TZ).tz_localize(None)
    cards = []
    for _, e in events.iterrows():
        summary, verdict = upcoming.history(e["kind"], data)
        hour = ""
        if e["time_et"]:
            h, m = map(int, str(e["time_et"]).split(":"))
            hour = f" · {h % 12 or 12}:{m:02d}{'pm' if h >= 12 else 'am'} ET"
        cards.append(
            f'<div class="kpi upcoming"><div class="kpi-label">'
            f'<b>{upcoming.when(e["date"], today)}</b> · {e["date"]:%a %b} {e["date"].day}{hour}</div>'
            f'<div class="up-title"><a href="{html.escape(e["source"])}" target="_blank" '
            f'rel="noopener">{html.escape(e["title"])}</a></div>'
            f'<div class="past">{html.escape(summary)}</div>'
            + (ui.verdict_badge(verdict, ui.verdict_tip(verdict, *_p_and_n(e["kind"], data)))
               if summary else "") + '</div>')
    st.subheader("Coming up", anchor=False)
    st.markdown(f'<div class="kpi-row" style="--cols:{len(cards)}">{"".join(cards)}</div>',
                unsafe_allow_html=True)
    ui.tip("Scheduled events that tend to move oil, with what Brent did after past ones. "
           "EIA reports come out every Wednesday at 10:30am ET (Thursday in a week with a "
           "federal holiday); OPEC+ and Fed dates are from their official calendars. Click "
           "an event's name for its official page.", "About this calendar")
    st.write("")


def _p_and_n(kind: str, data: dict) -> tuple[float, int, str]:
    """p-value, count and wording for the verdict tip of a calendar card."""
    results = data["react"][kind]["BRENT"][0]
    if kind == "inventory":
        values, what = results[results["category"] == "big_draw"]["day_1_pct"].dropna(), "report day for Brent"
        return data["sig"].p_value("BRENT", 1, values), len(values), what
    col = "decision"
    groups = {d: g["day_5_pct"].dropna() for d, g in results.groupby(col)}
    best = min(groups, key=lambda d: data["sig"].p_value("BRENT", 5, groups[d])
               if len(groups[d]) >= mk.MIN_EVENTS else 1)
    return data["sig"].p_value("BRENT", 5, groups[best]), len(groups[best]), "week for Brent"


def now_view(data: dict) -> None:
    archive = data["archive"]
    heat, heat_source = current_heat(data)
    results = data["news"][0] if heat_source == "world" else data["market_news"][0]

    # ---- 1. What's in the news now ------------------------------------------
    if not heat.empty:
        st.subheader("What's in the news", anchor=False)
        st.caption(f"Coverage over the last 3 days compared with normal, from "
                   f"{SOURCE_NAMES[heat_source].split(' (')[0].lower()} (data to "
                   f"{ui.day(heat['last_day'].max())}). For each topic: what Brent did "
                   "in the week after past news spikes.")
        card_css, opened = [], None
        for i, (_, row) in enumerate(heat.iterrows()):
            if i % 4 == 0:        # a fresh row of columns, so cards in a row match heights
                cols = st.columns(4)
            past = results[results["topic"] == row["topic"]]
            label, color, tint = status(row["heat"], row["enough"], row["big_enough"])
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
                    + ui.heat_gauge(row["heat"], color)
                    + (f"<div class='burst'>Mostly {ui.day(row['peak_day'], year=False)}: "
                       f"{row['peak_articles']} of {row['articles_3d']} stories</div>"
                       if row["enough"] and row["one_day"] and row["heat"] >= 1.5 else ""),
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
                        f"the next week<span class='rose'> · rose {(week > 0).mean():.0%} of "
                        "the time</span></div>"
                        + ui.verdict_badge(verdict, tip, quiet=True),
                        unsafe_allow_html=True)
                else:
                    st.caption("No past spikes to compare with yet.")
                if st.button("Read the stories →", key=f"open_{row['topic']}", type="tertiary"):
                    opened = row
        st.html(ui.CARD_CSS.replace("</style>", "\n".join(card_css) + "\n</style>"))
        if opened is not None:
            topic_dialog(opened["topic"], opened, data)
        st.write("")

    # ---- 2. Coming up: the next scheduled events ------------------------------
    coming_up(data)

    # ---- 3. Latest headlines ---------------------------------------------------
    st.subheader("Latest headlines", anchor=False)
    heads, is_live = latest_headlines(archive)
    headlines_section(heads, is_live, archive, data)
    st.button("Has a story like one of these happened before? →", type="tertiary",
              key="to_like", on_click=lambda: st.session_state.update(news_view="like"))


@st.fragment
def headlines_section(heads: pd.DataFrame, is_live: bool, archive: pd.DataFrame,
                      data: dict) -> None:
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
        articles, flashes = topic_stories(topic, heads, archive)
        if articles.empty and flashes.empty:
            st.info(f"No stories about {LABELS[topic].lower()} yet.")
            return
    if not is_live:
        st.caption("A news source didn't respond, so some of these are the newest saved "
                   "stories.")
    pool = _spread(articles, n=12 if topic else 30)
    expanded = st.session_state.get("more_headlines", False)
    shown = pool if expanded else pool.head(SHOW_FIRST)
    if len(shown):
        if topic:
            st.caption(f"The latest stories tagged *{LABELS[topic]}*, newest first, going "
                       f"back to {ui.day(shown['time'].min())}.")
        headline_list(shown, data)
        if len(pool) > SHOW_FIRST:
            label = "Show fewer stories ↑" if expanded else f"Show {len(pool) - SHOW_FIRST} more stories ↓"
            st.button(label, key="more_headlines_btn", type="tertiary",
                      on_click=lambda: st.session_state.update(more_headlines=not expanded))
        ui.tip(f"Articles from {articles['source'].nunique()} publishers' news feeds "
               "(energy press, shipping, world and Middle East news), newest first, at most "
               "three per publisher. Click a headline to read the full article on the "
               "publisher's site. Topic tags are assigned by keyword, so a few may be off.",
               "About these stories")
    if len(flashes):
        st.markdown("<div class='eyebrow' style='margin-top:1.2rem'>From the newswire</div>",
                    unsafe_allow_html=True)
        headline_list(flashes.head(6), data)
        ui.tip("Benzinga newswire flashes are one-line headlines with no article behind "
               "them. Where other outlets have covered the same story, we link to their "
               "articles; otherwise to the source the flash cites, or a short web search.",
               "About the newswire")


def topic_stories(topic: str, heads: pd.DataFrame, archive: pd.DataFrame):
    """(articles, flashes) about one topic: today's, plus saved publisher and
    Benzinga articles, so a quiet day still shows the latest coverage."""
    articles = heads[heads["kind"] == "article"] if len(heads) else heads
    flashes = heads[heads["kind"] == "flash"] if len(heads) else heads
    saved = pd.concat([feed_archive(), mn.oil_related(archive)], ignore_index=True)
    saved = saved[~saved["summary"].map(mn.is_flash)]
    pool = pd.concat([articles, saved], ignore_index=True).drop_duplicates("headline")

    def about(frame):
        return frame[frame["topics"].map(lambda ts: topic in ts)] if len(frame) else frame
    return about(pool), about(flashes)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def coverage_stories(version: float) -> pd.DataFrame:
    """The articles behind each topic's worldwide count (saved every 3 hours
    by the news job, see mediacloud_news.update_stories)."""
    import mediacloud_news
    t = mediacloud_news.load_stories()
    return t.assign(time=pd.to_datetime(t["time"]).dt.tz_localize("UTC"),
                    summary="", kind="article", date_only=True,
                    topics=t["headline"].map(lambda h: news.classify(str(h))))


@st.dialog("Latest stories", width="large")
def topic_dialog(topic: str, row, data: dict) -> None:
    """Opened by clicking a topic card: the stories behind its count, then
    the latest from our publishers' feeds."""
    import mediacloud_news
    label, color, _ = status(row["heat"], row["enough"], row["big_enough"])
    st.markdown(ui.status_line(label, color)
                + f"<div class='dialog-topic'>{LABELS[topic]}</div>", unsafe_allow_html=True)
    path = mediacloud_news.STORIES_PATH
    behind = coverage_stories(path.stat().st_mtime if path.exists() else 0)
    behind = behind[behind["topic"] == topic].sort_values("time", ascending=False)
    copies = int(behind["copies"].sum()) if len(behind) else 0
    st.caption(f"{row['heat']:.1f}× normal coverage over the last 3 days: "
               f"{row['articles_3d']} articles in worldwide news."
               + (f" Mostly {ui.day(row['peak_day'], year=False)}: {row['peak_articles']} of them."
                  if row["one_day"] else ""))

    st.markdown("**The stories behind the count**")
    if len(behind):
        st.caption(f"{len(behind)} different stories whose headline is about this topic"
                   + (f", published {copies} times across news sites" if copies > len(behind)
                      else "") + ". Click a headline to read it.")
        headline_list(behind.head(15), data)
    else:
        st.caption("No articles with this topic in the headline over the last 3 days. "
                   "The count comes from articles that only mention it in passing.")
    ui.tip("Worldwide coverage counts every article that mentions the topic anywhere, "
           "including the same story reprinted by many sites, and pages that only mention it "
           "in passing. This list keeps one copy of each story, and only those whose "
           "headline is about the topic.", "Why the count is bigger than this list")

    heads, _ = latest_headlines(data["archive"])
    articles, flashes = topic_stories(topic, heads, data["archive"])
    recent = articles[articles["time"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)]
    recent = recent[~recent["headline"].map(mediacloud_news._title_key)
                    .isin(set(behind["headline"].map(mediacloud_news._title_key)))]
    if len(recent):
        st.markdown("**More from our publishers, last 2 weeks**")
        headline_list(recent.sort_values("time", ascending=False).head(10), data)
    if len(flashes):
        st.markdown("<div class='eyebrow' style='margin-top:1rem'>From the newswire</div>",
                    unsafe_allow_html=True)
        headline_list(flashes.head(5), data)

    def to_topic() -> None:
        st.session_state.update(news_view="topics", news_topic=topic)
    if st.button("See this topic over time, and what oil did after past spikes →",
                 type="tertiary", on_click=to_topic, key="dialog_to_topic"):
        st.rerun()


MATCH_TABLE = {
    "day": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
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
    only the newest version is kept in memory. Past stories come from the
    Benzinga archive plus the saved publisher articles (news_feeds), so as that
    archive grows, matches include real articles from many outlets."""
    articles = feed_archive()
    if not articles.empty:
        articles = articles.assign(
            day=articles["time"].dt.tz_convert(mn.MARKET_TZ).dt.tz_localize(None).dt.normalize())
        _archive = pd.concat([_archive, articles], ignore_index=True).drop_duplicates("headline")
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
    version = f"{len(archive)}-{archive['time'].max()}-{len(feed_archive())}"
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
