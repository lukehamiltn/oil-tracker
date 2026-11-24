"""
Click a news spike's dot on any chart to see what that spike was about.

Used by every chart that marks news spikes: the Topics and Search coverage
charts (news_page.coverage_chart, on all three markets) and the gold and gas
price charts. The panel under the chart shows:
  - the topic, the day, and how far above normal coverage was
  - the biggest stories that day: saved ahead of time from Media Cloud
    (mediacloud_news.py spike-stories, in news.yml), or headlines from our own
    news archive. For a theme someone searched, which can't be saved ahead,
    a button fetches them live (about 30 seconds; remembered for a week)
  - what the price did over the next month, and after every other spike on
    the same topic

How a chart uses it:
    chosen = spike_details.pick("my_chart")             # before drawing
    ... draw the dots with customdata=spike_details.ids(spikes) ...
    spike_details.ring(fig, x, y)                       # around the chosen dot
    st.plotly_chart(fig, key="my_chart", **spike_details.CLICKABLE)
    spike_details.show(spikes, chosen, ...)              # the panel
"""

import datetime as dt
import html
import re
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import market_news as mn
import mediacloud_news as mcn
import ui

CLICKABLE = dict(on_select="rerun", selection_mode="points")
HINT = "Click any dot to see the biggest stories that day and what {name} did next."
LIVE_WAIT = "about 30 seconds"


# Which dot was clicked --------------------------------------------------------
def spike_id(topic, day) -> str:
    """One name per spike, kept on its dot. Stays the same when the chart is
    redrawn or the market changes, unlike a row number."""
    return f"spike|{topic}|{pd.Timestamp(day):%Y-%m-%d}"


def ids(spikes: pd.DataFrame, category: str = "topic") -> list[str]:
    return [spike_id(t, d) for t, d in zip(spikes[category], spikes["spike_day"])]


def _clicked(points: list) -> str | None:
    """The spike name stored on a clicked dot (clicks on the line are ignored).
    Plotly hands customdata back as a value, list or dict, depending on version."""
    for point in points:
        custom = point.get("customdata")
        values = (custom.values() if isinstance(custom, dict)
                  else custom if isinstance(custom, (list, tuple)) else [custom])
        for value in values:
            if isinstance(value, str) and value.startswith("spike|"):
                return value
    return None


def pick(chart_key: str) -> str | None:
    """The spike to show for this chart: the dot just clicked (the click
    arrives before the chart is redrawn), else the one clicked before. Only a
    NEW click changes it, so closing the panel isn't undone on the next rerun."""
    state = st.session_state.get(chart_key) or {}
    selection = state.get("selection", {}) if isinstance(state, dict) else getattr(state, "selection", {})
    points = selection.get("points", []) if isinstance(selection, dict) else getattr(selection, "points", [])
    now = _clicked(points)
    if now is not None and st.session_state.get(f"{chart_key}_last") != now:
        st.session_state[f"{chart_key}_pick"] = now
    st.session_state[f"{chart_key}_last"] = now
    return st.session_state.get(f"{chart_key}_pick")


def find(spikes: pd.DataFrame, chosen: str | None, category: str = "topic"):
    """The chosen spike's row, or None if it isn't on this chart."""
    if not chosen or spikes.empty:
        return None
    _, topic, day = chosen.split("|")
    hit = spikes[(spikes[category].astype(str) == topic)
                 & (pd.to_datetime(spikes["spike_day"]) == pd.Timestamp(day))]
    return hit.iloc[0] if len(hit) else None


def ring(fig: go.Figure, x, y) -> None:
    """A dark ring around the chosen dot."""
    if x is None or pd.isna(y):
        return
    fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers", hoverinfo="skip", showlegend=False,
                             marker=dict(size=22, color="rgba(0,0,0,0)",
                                         line=dict(color="#1d1d1b", width=2))))


# Stories from that day --------------------------------------------------------
@st.cache_data(ttl=60 * 60, show_spinner=False)
def saved_stories() -> pd.DataFrame:
    return mcn.load_spike_stories()


@st.cache_data(ttl=7 * 24 * 60 * 60, show_spinner=False, max_entries=300)
def live_stories(query: str, day: str, keywords: str | None) -> pd.DataFrame:
    """Ask Media Cloud for one day's biggest stories (slow, so remembered)."""
    import mediacloud.api as mc
    key = mcn.api_key()
    if not key:
        raise RuntimeError("no Media Cloud key")
    return mcn.day_stories(mc.SearchApi(key), query, dt.date.fromisoformat(day), keywords)


def _saved_for(market: str, topic: str, day: pd.Timestamp) -> pd.DataFrame | None:
    """Saved stories for this spike: a table (maybe empty, if Media Cloud had
    none), or None if this spike hasn't been fetched yet."""
    saved = saved_stories()
    if saved.empty:
        return None
    rows = saved[(saved["market"] == market) & (saved["topic"] == topic) & (saved["spike_day"] == day)]
    if rows.empty:
        return None
    return rows[rows["headline"].fillna("") != ""].sort_values("rank")


def _archive_heads(archive: pd.DataFrame | None, day: pd.Timestamp, keywords: str | None,
                   query: str | None) -> pd.DataFrame:
    """Stories from our own news archive, from the day before to the day after."""
    if archive is None or archive.empty or "day" not in archive:
        return pd.DataFrame()
    window = archive[(archive["day"] >= day - pd.Timedelta(days=1))
                     & (archive["day"] <= day + pd.Timedelta(days=1))]
    if window.empty:
        return window
    if keywords:
        words = re.sub(r"\((?!\?)", "(?:", keywords)
        hits = window[window["headline"].fillna("").str.contains(words, case=False, regex=True)]
    elif query and "text" in window:
        hits = window[mn.search_mask(window, query)]
    else:
        return window.iloc[0:0]
    return hits.sort_values("time", ascending=False).drop_duplicates("headline").head(6)


def _story_rows(stories: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Media Cloud stories in the shape news_page.headline_list draws."""
    return pd.DataFrame({
        "headline": stories["headline"].astype(str), "url": stories["url"].astype(str),
        "source": stories["source"].astype(str), "summary": "", "time": day.tz_localize("UTC"),
        "date_only": True, "copies": pd.to_numeric(stories["copies"], errors="coerce"),
        "kind": "article", "topics": [[] for _ in range(len(stories))]})


def _google_link(query: str, day: pd.Timestamp) -> str:
    """A Google News search for the theme, limited to the days around the spike."""
    words = re.sub(r"\s+", " ", query.replace("(", " ").replace(")", " ")).strip()
    start, end = day - pd.Timedelta(days=1), day + pd.Timedelta(days=1)
    url = (f"https://www.google.com/search?tbm=nws&q={quote(words)}"
           f"&tbs=cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{end:%m/%d/%Y}")
    return (f'<a class="more" href="{html.escape(url)}" target="_blank" rel="noopener">'
            f'Search Google News for those days ↗</a>')


def stories_section(market: str, topic: str, day: pd.Timestamp, query: str | None,
                    keywords: str | None, archive: pd.DataFrame | None, key: str) -> None:
    import news_page         # (imported here: news_page imports this file)
    saved = _saved_for(market, topic, day)
    live_key = f"{key}_live|{topic}|{day:%Y-%m-%d}"
    if (saved is None or saved.empty) and st.session_state.get(live_key) and query:
        try:
            with st.spinner(f"Asking worldwide news for that day's stories ({LIVE_WAIT})..."):
                saved = live_stories(query, f"{day:%Y-%m-%d}", keywords)
        except Exception as error:
            print(f"Spike stories unavailable: {error!r}")
            st.caption("Worldwide news didn't answer just now. Please try again in a minute.")
            st.session_state[live_key] = False
    if saved is not None and len(saved):
        on_topic = saved[saved["on_topic"].astype(bool)] if "on_topic" in saved else saved
        shown = on_topic if len(on_topic) >= 3 else saved
        ui.eyebrow("Biggest stories that day")
        news_page.headline_list(_story_rows(shown.head(6), day))
    else:
        heads = _archive_heads(archive, day, keywords, query)
        if len(heads):
            ui.eyebrow("Headlines around that day")
            if "topics" not in heads:
                heads = heads.assign(topics=[[] for _ in range(len(heads))])
            news_page.headline_list(heads)
        elif saved is not None:
            st.caption("Worldwide news had no story list for that day.")
        if saved is None and query and not st.session_state.get(live_key):
            if st.button(f"Find the biggest stories that day (takes {LIVE_WAIT})",
                         key=f"{live_key}_button", type="secondary", icon=":material/search:"):
                st.session_state[live_key] = True
                st.rerun(scope="fragment") if _in_fragment() else st.rerun()
    if query:
        st.markdown(_google_link(query, day), unsafe_allow_html=True)


def _in_fragment() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return bool(ctx and ctx.current_fragment_id)
    except Exception:
        return False


# What the price did ---------------------------------------------------------------
def _path_chart(path: pd.Series, color: str, name: str, key: str) -> None:
    fig = go.Figure(go.Scatter(x=path.index, y=path.values, mode="lines+markers",
                               line=dict(color=color, width=3), marker=dict(size=4),
                               hovertemplate="Day %{x}: %{y:+.1f}%<extra></extra>"))
    ui.style_event_chart(fig, f"% change in {name}", 260)
    fig.update_layout(hovermode="closest", margin=dict(l=8, r=8, t=12, b=8))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"{key}_spike_path")


def _moves_line(row, name: str) -> str:
    parts = []
    for h, when in ((1, "next day"), (5, "a week later"), (20, "a month later")):
        value = row.get(f"day_{h}_pct")
        if pd.notna(value):
            parts.append(f"{when} <b>{value:+.1f}%</b>")
    return f"{name}: " + " · ".join(parts) if parts else ""


def _others_line(spikes: pd.DataFrame, row, category: str, label: str, name: str, median: bool) -> str:
    if "day_5_pct" not in spikes:
        return ""
    others = spikes[(spikes[category] == row[category]) & (spikes["spike_day"] != row["spike_day"])]
    week = others["day_5_pct"].dropna()
    if len(week) < 3:
        return ""
    middle, word = (week.median(), "typically moved") if median else (week.mean(), "averaged")
    return (f"<div class='eyebrow' style='margin-top:0.8rem'>Every other “{html.escape(label)}” spike</div>"
            f"<div class='past'>{len(week)} other times: {name} {word} <b>{middle:+.1f}%</b> a week "
            f"later and rose {(week > 0).mean():.0%} of the time.</div>")


# The panel --------------------------------------------------------------------
def show(spikes: pd.DataFrame, chosen: str | None, *, market: str, name: str, paths: dict,
         labels: dict, colors: dict, queries: dict, keywords: dict | None = None,
         archive: pd.DataFrame | None = None, median: bool = False, category: str = "topic",
         key: str) -> None:
    """The panel for the clicked spike, or a hint to click one.
      market    "oil" / "gas" / "gold": where the saved stories are filed
      name      the price, as written in a sentence ("Brent", "Gold")
      paths     {event date: % path}, from event_study.compute_results
      labels, colors, queries, keywords   per topic (a search: one entry)
      archive   our own saved stories (with a "day" column), the fallback"""
    row = find(spikes, chosen, category)
    if row is None:
        st.caption(HINT.format(name=name.lower() if name == "Gold" else name))
        return
    topic, day = str(row[category]), pd.Timestamp(row["spike_day"]).normalize()
    label, color = labels.get(topic, topic), colors.get(topic, "#2a78d6")
    keywords = keywords or {}
    st.html(ui.CARD_CSS)
    with st.container(border=True):
        top_left, top_right = st.columns([6, 1], vertical_alignment="top")
        with top_left:
            ui.eyebrow(f"News spike · {ui.day(day, weekday=True)}")
            coverage = ""
            if pd.notna(row.get("ratio")):
                articles = f" ({int(row['articles']):,} articles)" if pd.notna(row.get("articles")) else ""
                coverage = f" · coverage {row['ratio']:.1f}× normal{articles}"
            st.markdown(ui.chip(html.escape(label), color)
                        + f"<span style='color:{ui.MUTED};font-size:0.9rem'>{coverage}</span>",
                        unsafe_allow_html=True)
        with top_right:
            if st.button("Close", key=f"{key}_close", type="tertiary", icon=":material/close:"):
                st.session_state[f"{key}_pick"] = None
                st.rerun(scope="fragment") if _in_fragment() else st.rerun()
        info, chart = st.columns([3, 2], gap="large")
        with info:
            stories_section(market, topic, day, queries.get(topic), keywords.get(topic), archive, key)
        with chart:
            path = paths.get(row["date"]) if "date" in row else None
            if path is not None:
                st.markdown(f"**{name} around this spike**")
                _path_chart(path, color, name, key)
                st.markdown(_moves_line(row, name), unsafe_allow_html=True)
            else:
                st.caption(f"Too recent: what {name.lower() if name == 'Gold' else name} did over the "
                           "following month isn't known yet.")
            st.markdown(_others_line(spikes, row, category, label, name, median), unsafe_allow_html=True)
