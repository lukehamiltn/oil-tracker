"""
The News tab for one market (natural gas, gold): the same tools on every
market page, each set up by a Spec (GAS, GOLD below).

  Today             why the price moved today, the news topics with what the
                    price did after past spikes, and the latest headlines,
                    each with a "Last time: ..." line
  Like this before  pick one of today's headlines (or type one): the past
                    stories worded most like it, and what the price did after
  Topics            one topic's worldwide coverage since 2015 with every spike
                    marked, the price after each spike, and all topics compared
  Search            any theme in worldwide news (Media Cloud, about 1,600
                    sites since 2015, searched live): the days it suddenly
                    dominated the news, and what the price did next

Past stories come from a saved news archive (Benzinga via Alpaca, since 2015)
plus the saved publisher articles, keeping those about this market. (Gold's
archive only starts in mid-2026, so gold has no Like this before yet.)

Gas shows TYPICAL (median) moves: the daily Henry Hub spot price has rare
huge spikes on very cold days (+380% in a week in January 2024), and one of
those would swamp an average of ten stories. Gold shows averages, but (like
the oil site) only calls something a pattern if the typical move agrees.

The oil site has its own, older version of these tools (news_page.py).
"""

import html
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import pandas as pd
import streamlit as st

import daily_move as dm
import event_study as es
import market_news as mn
import markets as mk
import news
import news_feeds as nf
import news_page
import ui


@dataclass(frozen=True)
class Spec:
    key: str                  # "gas": used in widget keys ("gas_news_view")
    market: str               # price key in markets.py ("NATGAS")
    name: str                 # what the price is called ("Henry Hub")
    word: str                 # the market in a sentence ("gas")
    terms: re.Pattern         # a story is about this market if it matches
    subject: str              # the market in price-move headlines (daily_move.py)
    topics: dict              # news.GAS_TOPICS ...
    examples: list            # ideas for the search box
    color: str
    unit: str                 # "per MMBtu"
    typical: bool             # show the median move (True) or the average
    like_placeholder: str
    search_placeholder: str
    search_hint: str          # an OR example for the search caption
    archive_name: str         # the backup search: "energy-market news"
    quiet_note: str           # why-today: when no headline explains the move
    archive_recent: bool = False   # add the last days' archive stories to the headlines
    like: bool = True              # past-story matching (needs years of saved stories)
    saved_terms: re.Pattern = field(default=nf.OIL_TERMS)   # which saved feed articles

    @property
    def keys(self) -> list:
        return list(self.topics)

    @property
    def labels(self) -> dict:
        return {k: t["label"] for k, t in self.topics.items()}

    @property
    def colors(self) -> dict:
        return {k: t["color"] for k, t in self.topics.items()}

    def classify(self, title: str) -> list[str]:
        title = str(title).lower()
        return [k for k, t in self.topics.items() if re.search(t["keywords"], title)]

    def middle(self, values: pd.Series) -> float:
        return values.median() if self.typical else values.mean()

    @property
    def middle_word(self) -> str:      # "Henry Hub typically +1.2%" / "Gold averaged +1.2%"
        return "typically" if self.typical else "averaged"

    @property
    def in_text(self) -> str:          # mid-sentence: "Henry Hub", but "gold" not "Gold"
        return self.word if self.name.lower() == self.word else self.name

    @property
    def center(self) -> str:           # for ui.event_paths / comparison_section
        return "median" if self.typical else "mean"


GAS = Spec(
    key="gas", market="NATGAS", name="Henry Hub", word="gas",
    # ("gas prices" alone usually means petrol at the pump, so it isn't matched)
    terms=re.compile(r"natural gas|\bnat ?gas\b|\blng\b|henry hub|gas (?:storage|field|pipeline|export|supplies)"
                     r"|gazprom|nord stream|\bttf\b|liquefied", re.I),
    subject=dm.GAS_SUBJECT, topics=news.GAS_TOPICS,
    examples=['"Freeport LNG"', '"Nord Stream"', '"polar vortex"', '"Sabine Pass"', "Gazprom",
              '"Henry Hub"', '"natural gas" "data center"', '"Waha"', '"Qatar" LNG', '"gas storage"'],
    color="#0f766e", unit="per MMBtu", typical=True,
    like_placeholder="e.g. Freeport LNG plant shut after fire", search_placeholder='"LNG export"',
    search_hint='"Freeport LNG" OR "Sabine Pass"', archive_name="energy-market news",
    quiet_note="No gas headline in the last two days explains the move yet. Gas often moves on "
               "weather forecasts, which rarely make the news.",
)

GOLD_SUBJECT = r"\b(gold|bullion|precious metals?|gold futures|gold prices?)\b"
GOLD = Spec(
    key="gold", market="GOLD", name="Gold", word="gold",
    terms=nf.GOLD_TERMS, subject=GOLD_SUBJECT, topics=news.GOLD_TOPICS,
    examples=['"central bank" gold', '"safe haven"', '"rate cut"', '"record high" gold', "tariffs gold",
              '"gold ETF"', "Diwali gold", '"de-dollarization"', '"Silicon Valley Bank"', '"debt ceiling"'],
    color="#b8860b", unit="an ounce", typical=False,
    like_placeholder="e.g. Gold jumps as Fed signals rate cuts", search_placeholder='"safe haven" gold',
    search_hint='"debt ceiling" OR "government shutdown"', archive_name="gold-market news",
    quiet_note="No gold headline in the last two days explains the move yet. Gold often moves with "
               "interest rates and the dollar, without a gold story behind it.",
    # The gold story archive only starts in mid-2026 (Alpaca keeps a few months
    # of news), too little to match today's stories against: no "Like this
    # before" until it has grown.
    archive_recent=True, saved_terms=nf.GOLD_TERMS, like=False,
)
SPECS = {s.key: s for s in (GAS, GOLD)}
MIN_PAST = 4                  # fewer close matches than this: no "Last time" line
VIEWS = {"now": "Today", "like": "Like this before", "topics": "Topics", "search": "Search"}


# Stories --------------------------------------------------------------------------
@st.cache_data(ttl=60 * 60, show_spinner=False)
def saved_articles(key: str) -> pd.DataFrame:
    """The saved publisher articles about this market."""
    return nf.load_archive(SPECS[key].saved_terms)


def about(spec: Spec, t: pd.DataFrame) -> pd.DataFrame:
    return t[(t["headline"].fillna("") + " " + t["summary"].fillna("")).str.contains(spec.terms)]


def pool(spec: Spec, archive: pd.DataFrame) -> pd.DataFrame:
    """Every saved story about this market: the news archive plus the
    publisher articles, with a 'day' (New York date) column."""
    articles = saved_articles(spec.key)
    if not articles.empty:
        articles = articles.assign(
            day=articles["time"].dt.tz_convert(mn.MARKET_TZ).dt.tz_localize(None).dt.normalize())
    both = pd.concat([archive, articles], ignore_index=True).drop_duplicates("headline")
    both["summary"] = both["summary"].fillna("")
    # (the searchable text; publisher articles don't come with it)
    both["text"] = both["text"].fillna((both["headline"].fillna("") + " " + both["summary"]).str.lower())
    return about(spec, both)


def _version(spec: Spec, archive: pd.DataFrame) -> str:
    return f"{spec.key}-{len(archive)}-{archive['time'].max()}-{len(saved_articles(spec.key))}"


@st.cache_data(ttl=15 * 60, show_spinner=False)
def live_headlines(key: str, _archive: pd.DataFrame | None = None) -> pd.DataFrame:
    """Recent articles about this market from the publishers' feeds (and,
    for gold, the last days of the news archive)."""
    spec = SPECS[key]
    try:
        found = nf.fetch(oil_only=False)
    except Exception as error:
        print(f"News feeds unavailable: {error}")
        found = pd.DataFrame(columns=nf.COLUMNS)
    if found.empty:
        saved = saved_articles(key)
        since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)
        found = saved[saved["time"] >= since] if not saved.empty else saved
    if spec.archive_recent and _archive is not None and not _archive.empty:
        since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)
        recent = _archive[_archive["time"] >= since]
        recent = recent.assign(url=[mn.read_url(r) for _, r in recent.iterrows()])
        found = pd.concat([found, recent[nf.COLUMNS]], ignore_index=True)
    if found.empty:
        return found
    mine = about(spec, found).copy()
    mine["topics"] = mine["headline"].map(spec.classify)
    return mine.sort_values("time", ascending=False).drop_duplicates("headline")


@st.cache_resource(show_spinner="Indexing past headlines...", max_entries=2)
def matcher(_archive: pd.DataFrame, version: str, key: str):
    """Built once per archive version, from this market's stories only."""
    return mn.build_matcher(pool(SPECS[key], _archive), related=lambda t: t)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False, max_entries=300)
def past_matches(text: str, before: pd.Timestamp, _archive: pd.DataFrame, _prices: pd.Series,
                 version: str, key: str) -> tuple[pd.DataFrame, dict]:
    """(results, paths) of the price after the past stories most like `text`."""
    found = mn.similar(matcher(_archive, version, key), text, before)
    if found.empty:
        return pd.DataFrame(), {}
    found = found.assign(date=found["day"], description=found["headline"])
    return es.compute_results(_prices, found)


def _matches(spec, text, before, archive, prices):
    return past_matches(text, before.floor("h"), archive, prices, _version(spec, archive), spec.key)


def history_line(spec: Spec, h, prices: pd.Series, archive: pd.DataFrame, sig: mk.Significance) -> str:
    """'Last time: 6 similar stories -> Henry Hub typically +2.1% a week later
    (could be noise) - See them'. Empty without enough close matches."""
    if archive.empty or not spec.like:
        return ""
    before = pd.Timestamp(h["time"]) - pd.Timedelta(days=14)
    results, _ = _matches(spec, str(h["headline"]), before, archive, prices)
    week = results["day_5_pct"].dropna() if not results.empty else pd.Series(dtype=float)
    if len(week) < MIN_PAST:
        return ""
    verdict = sig.check(spec.market, 5, week)
    text, color = mk.VERDICTS[verdict]
    tone = "#1d1d1b" if verdict in ("strong", "possible") else ui.MUTED
    link = "?like=" + quote(str(h["headline"])[:300])
    return (f'<div class="history">Last time: {len(week)} similar stories → {spec.name} {spec.middle_word} '
            f'<b style="color:{tone}">{spec.middle(week):+.1f}%</b> a week later · '
            f'<span style="color:{color}">{text.lower()}</span> · '
            f'<a href="{link}" target="_self">See them →</a></div>')


def headline_rows(spec: Spec, heads: pd.DataFrame, prices: pd.Series = None, archive: pd.DataFrame = None,
                  sig: mk.Significance = None) -> None:
    """Headlines, each (given prices, archive and sig) with a 'Last time' line
    when there are enough close past matches."""
    rows = []
    for _, h in heads.iterrows():
        past = ""
        if sig is not None:
            try:
                past = history_line(spec, h, prices, archive, sig)
            except Exception as error:
                print(f"No history line: {error!r}")
        title = html.escape(ui.headline_case(str(h["headline"])))
        link = f'<a href="{html.escape(str(h["url"]))}" target="_blank" rel="noopener">{title}</a>'
        summary = html.escape(str(h.get("summary") or ""))[:220]
        chips = "".join(ui.chip(news.topic_info(t)["label"], news.topic_info(t)["color"]) for t in h["topics"])
        rows.append(f'<div class="headline">{link}<div class="summary">{summary}</div>'
                    f'<div class="meta">{chips}<span class="publisher">{html.escape(str(h["source"]))}</span>'
                    f' · {news_page._ago(h["time"])}</div>{past}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


# Today ----------------------------------------------------------------------------
def why_today(spec: Spec, q: dict | None, prices: pd.Series, heads: pd.DataFrame, heat: pd.DataFrame,
              show_rows) -> None:
    """Today's move, how unusual it is, the headlines most likely behind it,
    and what the price did the week after past days like it."""
    if not q or q.get("change_pct") is None:
        return
    change, t = q["change_pct"], q["time"]
    is_today = pd.Timestamp.now(tz=t.tz).date() == t.date()
    stats = dm.move_stats(prices, change)
    up = change >= 0
    color = "#1d8a5e" if up else "#c43a39"
    clock = f"{t.hour % 12 or 12}:{t:%M} {'pm' if t.hour >= 12 else 'am'} ET"
    quiet = abs(change) < (0.5 if spec.market == "GOLD" else 1)
    years = f"trading days in the past {dm.HISTORY_YEARS} years"
    rank = (f"A quiet day: a smaller move than {100 - stats['bigger_than']:.0f}% of {years}"
            if quiet else f"A bigger move than {stats['bigger_than']:.0f}% of {years}")
    word = spec.word.capitalize()
    st.subheader(f"Why {spec.word} moved today" if is_today else f"{word}'s last session", anchor=False)
    with st.container(border=True, key=f"{spec.key}_why_today"):
        a, b = st.columns([2, 3], gap="large")
        with a:
            ui.eyebrow(f"{spec.name} · {ui.day(t, year=False, weekday=True)}, {clock}")
            st.markdown(f"<div class='why-move' style='color:{color}'>{'▲' if up else '▼'} {change:+.1f}%</div>"
                        f"<div class='why-price'>${q['price']:,.2f} {spec.unit}</div><div class='why-rank'>{rank}</div>",
                        unsafe_allow_html=True)
            diff = stats["avg_ahead"] - stats["base_avg"]
            verdict = ("about the same as any week, so a day like this says little about the next one"
                       if abs(diff) < (0.4 if spec.market == "GOLD" else 1)
                       else f"{'better' if diff > 0 else 'worse'} than a typical week")
            st.markdown("<div class='card-rule' style='margin:0.7rem 0 0.5rem'></div>"
                        "<div class='eyebrow'>After past days like this</div>"
                        f"<div class='past'>On the {stats['n']:,} days since {stats['since']:%Y} when {spec.word} "
                        f"{dm.band_text(change, stats['band'])}, it averaged <b>{stats['avg_ahead']:+.1f}%</b> over "
                        f"the next week and rose {stats['pct_up']:.0f}% of the time: {verdict} "
                        f"({stats['base_avg']:+.1f}%, rose {stats['base_up']:.0f}%).</div>", unsafe_allow_html=True)
        with b:
            ui.eyebrow("What the news says")
            hot = [] if heat.empty else list(heat[heat["enough"] & (heat["heat"] >= 1.5)]["topic"])
            reasons = (dm.likely_reasons(heads, change, hot, subject=spec.subject, hours=48)
                       if len(heads) else heads)
            if len(reasons):
                show_rows(reasons)
            else:
                st.caption(spec.quiet_note)
            ui.tip(f"Headlines from the last two days that report {spec.word} moving the same way as the market "
                   f"(\"{word} jumps as...\"), which usually give the reason, then the newest stories on the "
                   f"busiest {spec.word} topics. They are the likeliest explanations, not proof of cause.",
                   "How these are picked")


def topic_cards(spec: Spec, data: dict, heat: pd.DataFrame, open_stories) -> None:
    """One card per news topic: coverage now vs normal, and what the price did
    the week after past spikes. `open_stories(topic, row)` opens its stories."""
    if heat.empty:
        st.info(f"{spec.word.capitalize()} news coverage is still being collected. It's refreshed every 3 hours.")
        return
    st.subheader(f"What's in the {spec.word} news", anchor=False)
    st.caption(f"Coverage of each topic over the last 3 days compared with normal, in about 1,600 news sites "
               f"(data to {ui.day(heat['last_day'].max())}). For each: what {spec.in_text} did the week after past spikes.")
    results = data["spike_react"][0]
    sig = data["sig"]
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
                p = sig.p_value(spec.market, 5, week)
                verdict = sig.verdict(p, week.notna().sum())
                lead = f"{spec.word.capitalize()} typically" if spec.typical else f"{spec.word.capitalize()} averaged"
                st.markdown("<div class='card-rule'></div>"
                            f"<div class='eyebrow' style='margin-top:0.4rem'>After {len(past)} past spikes</div>"
                            f"<div class='past'>{lead} <b>{spec.middle(week):+.1f}%</b> the next week · rose "
                            f"{(week > 0).mean():.0%} of the time</div>"
                            + ui.verdict_badge(verdict, ui.verdict_tip(verdict, p, int(week.notna().sum()),
                                                                      f"week for {spec.word}"), quiet=True),
                            unsafe_allow_html=True)
            else:
                st.caption("No past spikes to compare with yet.")
            if st.button("Latest stories →", key=f"{spec.key}_stories_{row['topic']}", type="tertiary"):
                open_stories(row["topic"], row)


# Like this before -----------------------------------------------------------------
@st.fragment
def like_this_before(spec: Spec, prices: pd.Series, sig: mk.Significance, heads: pd.DataFrame,
                     archive: pd.DataFrame) -> None:
    st.subheader("Has this happened before?", anchor=False)
    if archive.empty:
        st.info("The news archive isn't available right now. Please try again later.")
        return
    st.caption(f"Pick one of today's {spec.word} headlines, or type your own. We find the past {spec.word} "
               f"stories worded most like it, and show what {spec.in_text} did after each one.")
    options = heads["headline"].tolist() if not heads.empty else []
    # Headlines that have close past matches first (others would show nothing)
    if options:
        found = {}
        for _, h in heads.head(30).iterrows():
            r, _ = _matches(spec, str(h["headline"]), pd.Timestamp(h["time"]) - pd.Timedelta(days=14),
                            archive, prices)
            found[h["headline"]] = len(r)
        options = sorted(options, key=lambda h: found.get(h, 0) < MIN_PAST)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown(f"**Today's {spec.word} headlines**")
        if options:
            with st.container(height=340, key=f"{spec.key}_like_list"):
                meta = {h["headline"]: f"{h['source']} · {news_page._ago(h['time'])}" for _, h in heads.iterrows()}
                picked = st.radio("Today's headline", options, index=0, key=f"{spec.key}_like_pick",
                                  format_func=lambda h: f"{news_page._plain(h)}  \n:gray[{news_page._plain(meta.get(h, ''))}]",
                                  label_visibility="collapsed")
        else:
            picked = None
            st.caption(f"No {spec.word} headlines right now.")
    with c2:
        st.markdown("**Or type a headline**")
        typed = st.text_input("Or type a headline", key=f"{spec.key}_like_typed",
                              placeholder=spec.like_placeholder, label_visibility="collapsed")
        st.caption("Typing here overrides the picked headline. Clear it to go back to the list.")
    text = typed.strip() or picked
    if not text:
        return
    before = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)
    if not typed.strip() and not heads.empty:
        row = heads[heads["headline"] == picked]
        if len(row):
            before = row["time"].iloc[0] - pd.Timedelta(days=14)
    results, paths = _matches(spec, text, before, archive, prices)
    if results.empty:
        st.info(f"No past {spec.word} stories are worded closely enough to compare. Try a more specific "
                "headline (names of places, companies or events help most).")
        return
    day, week, month = results["day_1_pct"], results["day_5_pct"], results["day_20_pct"]
    verdict = lambda h, v: mk.VERDICTS[sig.check(spec.market, h, v)][0]
    what = "typical" if spec.typical else "average"
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Similar past stories", len(results), border=True)
    m2.metric(f"{spec.name} next day: {what}", f"{spec.middle(day):+.1f}%", verdict(1, day),
              delta_color="off", delta_arrow="off", border=True)
    m3.metric(f"{spec.name} a week later: {what}", f"{spec.middle(week):+.1f}%",
              f"{verdict(5, week)} · rose {(week > 0).mean():.0%}", delta_color="off", delta_arrow="off", border=True)
    m4.metric(f"{spec.name} a month later: {what}", f"{spec.middle(month):+.1f}%",
              f"{verdict(20, month)} · rose {(month > 0).mean():.0%}", delta_color="off", delta_arrow="off",
              border=True)
    ui.event_paths(results, paths, spec.color, news_page.MATCH_TABLE, key=f"{spec.key}_like_paths",
                   market=spec.name, center=spec.center)
    ui.tip("Similarity is based on shared wording (rare words like place and company names count most), "
           "so check the headlines to judge how alike the stories really are. With a handful of matches, "
           "one big move can swing the result"
           + (", and gas moves a lot. That's why the numbers above are the typical (median) move: half the "
              "stories were followed by more, half by less." if spec.typical else
              ", which is why each number is also checked on the typical (median) move before it's called a "
              "pattern."), "How matches are found")


# Topics ---------------------------------------------------------------------------
@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def spikes_with_headlines(_spikes: pd.DataFrame, _archive: pd.DataFrame, version: str, key: str) -> pd.DataFrame:
    """The news spikes, each with a headline from around that day."""
    spec = SPECS[key]
    stories = pool(spec, _archive)

    def match(window, spike):
        words = re.sub(r"\((?!\?)", "(?:", spec.topics[spike["topic"]]["keywords"])
        return window["headline"].fillna("").str.contains(words, case=False, regex=True)
    return mn.add_headlines(_spikes, stories, match)


@st.fragment
def topics_view(spec: Spec, prices: pd.Series, data: dict, archive: pd.DataFrame) -> None:
    st.subheader("One topic over time", anchor=False)
    timelines = data["timelines"]
    if timelines.empty:
        st.info(f"{spec.word.capitalize()} news coverage is still being collected.")
        return
    topic = ui.topic_picker("Change topic", spec.keys, spec.labels, spec.colors, key=f"{spec.key}_news_topic",
                            default=spec.keys[0])
    results, paths = data["spike_react"]
    if not results.empty and not archive.empty:
        with_heads = spikes_with_headlines(data["spikes"], archive, _version(spec, archive), spec.key)
        results = results.merge(with_heads[["date", "topic", "headline"]], on=["date", "topic"], how="left")
        results["description"] = [f"{h}<br>{d}" if isinstance(h, str) and h else d
                                  for h, d in zip(results["headline"], results["description"])]
    t = timelines[timelines["topic"] == topic]
    spikes = results[results["topic"] == topic] if not results.empty else results
    ui.tip(f"`{spec.topics[topic]['query']}`", "Search used for worldwide news")
    news_page.coverage_chart(t, spikes, spec.colors[topic], key=f"{spec.key}_news_cov", source="world")
    st.markdown(f"**{spec.name} after each of the {len(spikes)} news spikes**")
    ui.event_paths(spikes, paths, spec.colors[topic], news_page.SPIKE_TABLE, key=f"{spec.key}_topic_paths",
                   market=spec.name, center=spec.center)
    if not results.empty:
        st.divider()
        st.subheader("All topics compared", anchor=False)
        available = [k for k in spec.keys if k in set(results["topic"])]
        ui.comparison_section(prices, results, paths, "topic", available, spec.labels, spec.colors,
                              key=f"{spec.key}_news_cmp", market=spec.name, sig=data["sig"],
                              market_key=spec.market, center=spec.center)
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
    """The backup: daily counts in the saved news archive."""
    return mn.counts(_archive, mn.search_mask(_archive, query), "search")


@st.fragment
def search_view(spec: Spec, prices: pd.Series, sig: mk.Significance, archive: pd.DataFrame) -> None:
    st.subheader("Search the news", anchor=False)
    st.caption("Searches worldwide news (about 1,600 English-language sites, since 2015) for any theme. "
               f"We find the days it suddenly dominated the news and show what {spec.in_text} did next. Put exact "
               f"phrases in quotes; use OR for alternatives, e.g. `{spec.search_hint}`.")
    pick = st.pills("Try one", spec.examples, key=f"{spec.key}_news_example")
    with st.form(f"{spec.key}_news_search", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        typed = c1.text_input("News theme", placeholder=spec.search_placeholder)
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
        st.caption(f"Worldwide news search is busy right now, so this searches our saved {spec.archive_name} "
                   "instead (far fewer stories). Try again in a minute for the full search.")
        t, source = archive_counts(query, archive, _version(spec, archive)).assign(topic="search"), "market"
    total = int(t["articles"].sum())
    if not total:
        st.info(f"No stories found for {query}. Try fewer or simpler words.")
        return
    spikes = news.find_spikes(t, source=source, min_articles=None if source == "world" else 3)
    results, paths = es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {})
    st.markdown(f"**{total:,} stories mention {html.escape(query)}**")
    shown = results if not results.empty else pd.DataFrame(columns=["spike_day", "description"])
    news_page.coverage_chart(t, shown, spec.color, key=f"{spec.key}_search_cov", source=source)
    if results.empty:
        st.info("This theme never spiked sharply enough to count as a news event "
                f"(needs {news.SPIKE_RATIO:.0f}× its normal coverage on a busy day).")
    else:
        week = results["day_5_pct"]
        c1, c2, c3 = st.columns(3)
        c1.metric("News spikes found", len(results), border=True)
        c2.metric(f"{spec.name} a week later: {'typical' if spec.typical else 'average'}",
                  f"{spec.middle(week):+.1f}%", mk.VERDICTS[sig.check(spec.market, 5, week)][0],
                  delta_color="off", delta_arrow="off", border=True)
        c3.metric(f"{spec.name} rose afterwards", f"{(week > 0).mean():.0%}", border=True)
        ui.event_paths(results, paths, spec.color, news_page.SPIKE_TABLE, key=f"{spec.key}_search_paths",
                       market=spec.name, center=spec.center)
    if not archive.empty:
        stories = pool(spec, archive)
        recent = stories[mn.search_mask(stories, query)].sort_values("time", ascending=False).head(8)
        if len(recent):
            with st.expander(f"Most recent matching {spec.word} stories we've saved"):
                news_page.headline_list(recent.assign(topics=[[] for _ in range(len(recent))]))


# Topic stories (opened from a topic card) ---------------------------------------
@st.dialog("Latest stories", width="large")
def topic_dialog(spec: Spec, topic: str, row, heads: pd.DataFrame, archive: pd.DataFrame, show_rows) -> None:
    """The recent stories about one topic, from our publishers and the archive."""
    label, color, _ = news_page.status(row["heat"], row["enough"], row["big_enough"])
    st.markdown(ui.status_line(label, color) + f"<div class='dialog-topic'>{spec.labels[topic]}</div>",
                unsafe_allow_html=True)
    st.caption(f"{row['heat']:.1f}× normal coverage over the last 3 days: {row['articles_3d']:,} articles "
               "in worldwide news.")
    stories = pd.concat([heads, pool(spec, archive)], ignore_index=True).drop_duplicates("headline")
    stories = stories[stories["time"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)]
    words = re.sub(r"\((?!\?)", "(?:", spec.topics[topic]["keywords"])
    hits = stories[stories["headline"].fillna("").str.contains(words, case=False, regex=True)]
    if hits.empty:
        st.caption("None of our sources had a headline about this in the last two weeks. The worldwide "
                   "count includes articles that only mention it in passing.")
    else:
        st.markdown("**Latest stories, last 2 weeks**")
        hits = hits.assign(topics=hits["headline"].map(spec.classify))
        show_rows(hits.sort_values("time", ascending=False).head(12))

    def to_topic() -> None:
        st.session_state.update({f"{spec.key}_news_view": "topics", f"{spec.key}_news_topic": topic})
    if st.button(f"See this topic over time, and what {spec.word} did after past spikes →", type="tertiary",
                 on_click=to_topic, key=f"{spec.key}_dialog_to_topic"):
        st.rerun()


def pick_view(spec: Spec) -> str:
    """The row of buttons at the top of the News tab. A 'See them ->' link
    under a headline opens that story in Like this before."""
    view_key = f"{spec.key}_news_view"
    st.session_state.setdefault(view_key, "now")
    views = {k: v for k, v in VIEWS.items() if spec.like or k != "like"}
    asked = st.query_params.get("like") if spec.like else None
    if asked:
        st.session_state[view_key] = "like"
        st.session_state[f"{spec.key}_like_typed"] = asked
        del st.query_params["like"]
    view = st.segmented_control("Section", list(views), key=view_key, format_func=views.get,
                                label_visibility="collapsed") or "now"
    st.write("")
    return view
