"""The Storylines view: big stories that come back in waves, and what the
market did during each wave. Used by the oil site (News > Storylines, about
Brent) and the gas site (Storylines tab, about Henry Hub). Calculations are
in storylines.py."""

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import live_prices
import storylines as sl
import ui

# Each market's storylines, saved coverage, and how its price is named
MARKETS = {
    "oil": {"stories": sl.STORYLINES, "path": sl.PATH, "name": "Brent", "live": "BRENT", "unit": "$",
            "state": "storyline",
            "overlap_example": " (the 2025–26 Venezuela wave overlaps the Iran war, for example)"},
    "gas": {"stories": sl.GAS_STORYLINES, "path": sl.GAS_PATH, "name": "Gas", "live": "NATGAS", "unit": "$",
            "state": "gas_storyline",
            "overlap_example": " (the 2022 Europe crisis and the Russian pipeline cuts ran together, for example)"},
}


@st.cache_data(ttl=30 * 60, show_spinner=False)
def _coverage(path: str, version: float) -> pd.DataFrame:
    return sl.load(Path(path))


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _extended(_official: pd.Series, live: str, last_day: str) -> pd.Series:
    """Official prices, carried to today with scaled futures (see live_prices.extend)."""
    try:
        return live_prices.extend(_official, live)[0]
    except Exception:
        return _official


def summary_of(table: pd.DataFrame, key: str, prices: pd.Series) -> dict | None:
    cov = sl.coverage(table, key)
    if cov["smooth"].dropna().empty:
        return None
    w = sl.waves(cov)
    if w.empty:
        return None
    last_day = cov.index[-1]
    level = (cov["smooth"] / cov["long_run"]).dropna()
    now_x = level.iloc[-1]
    newest = w.iloc[-1]
    # The newest wave is still running if it only just dipped, or if coverage
    # has stayed far above its long-run normal ever since (a story that runs
    # all year starts to look "normal" next to the past year, which is what
    # the wave finder compares with)
    since_end = level[level.index > newest["end"]]
    ongoing = ((last_day - newest["end"]).days <= 10
               or (len(since_end) > 0 and (since_end >= sl.WAVE_RATIO).all()))
    w = w.copy()
    if ongoing:
        w.iloc[-1, w.columns.get_loc("end")] = last_day
    major = sl.major(w)
    # The wave to feature: a running one, else the newest big one
    if ongoing:
        latest = w.iloc[-1]
        if latest["start"] not in set(major["start"]):
            major = pd.concat([w.iloc[[-1]], major]).sort_values("start", ascending=False)
    else:
        latest = major.iloc[0] if len(major) else newest
    return {
        "cov": cov, "waves": w, "major": major, "latest": latest,
        "ongoing": ongoing, "now_x": now_x,
        "moves": sl.wave_moves(prices, latest),
    }


def render(data: dict) -> None:
    """The oil site's Storylines view."""
    render_for("oil", data["markets"]["BRENT"], data["archive"])


def render_for(kind: str, official: pd.Series, archive: pd.DataFrame) -> None:
    m = MARKETS[kind]
    stories, name = m["stories"], m["name"]
    path = m["path"]
    table = _coverage(str(path), path.stat().st_mtime if path.exists() else 0)
    if table.empty:
        st.info("Storyline data isn't available yet. It's refreshed every 3 hours.")
        return
    prices = _extended(official, m["live"], str(official.index[-1]))
    keys = [k for k in stories if k in set(table["storyline"])]
    summaries = {k: summary_of(table, k, prices) for k in keys}
    keys = [k for k in keys if summaries[k] is not None]
    if not keys:
        st.info("No storyline has had a big wave of coverage yet.")
        return
    # Busiest storyline right now first
    keys.sort(key=lambda k: summaries[k]["now_x"], reverse=True)

    st.subheader("Storylines", anchor=False)
    st.caption(f"Big stories that run for months and come back in waves. For each one: how much worldwide "
               f"news it gets, when its waves came, and what {name.lower() if kind == 'gas' else name} prices did "
               "during them.")
    state = m["state"]
    if st.session_state.get(state) not in keys:
        st.session_state[state] = keys[0]
    key = st.pills("Storyline", keys, key=state, label_visibility="collapsed",
                   format_func=lambda k: stories[k]["label"]) or keys[0]
    story, s = stories[key], summaries[key]
    latest, cov, moves = s["latest"], s["cov"], s["moves"]

    st.markdown(f"<div class='dialog-topic'>{story['label']}</div>"
                f"<div class='why-rank' style='margin-bottom:0.8rem'>{story['summary']}</div>",
                unsafe_allow_html=True)

    # Other storylines' big waves running at the same time (they move prices too)
    overlaps = []
    for other in keys:
        if other == key:
            continue
        for _, w in summaries[other]["major"].iterrows():
            shared = (min(w["end"], latest["end"]) - max(w["start"], latest["start"])).days
            if shared >= 30:
                overlaps.append(stories[other]["label"])
                break
    price_note = f"low {moves['low']:+.0f}%, high {moves['high']:+.0f}% in its first 6 months"
    if overlaps:
        price_note = f"also during: {', '.join(overlaps)} · " + price_note

    end_text = "now" if s["ongoing"] else ui.day(latest["end"])
    level = ("far above normal" if s["now_x"] >= 5 else "above normal" if s["now_x"] >= 2
             else "close to normal")
    ui.kpi_row([
        ("Coverage now", f"{s['now_x']:.1f}× normal", f"{level} · last 7 days vs its median since 2015", None),
        ("Latest wave", "Ongoing" if s["ongoing"] else "Ended",
         f"{ui.day(latest['start'])} – {end_text} · peak {latest['peak_x']:.0f}× normal on {ui.day(latest['peak'])}",
         None),
        (f"{name} during this wave", f"{moves['whole']:+.0f}%", price_note, None),
        ("Waves since 2015", f"{len(s['waves'])}", f"{len(s['major'])} big ones compared below", None),
    ])

    timeline(kind, key, story, cov, s["waves"], latest, prices, name)
    turning_points(key, cov, latest, prices, archive, stories, name)
    compare_waves(kind, story, s["major"], latest, prices, name)
    ui.tip("Coverage is the storyline's share of all stories in about 1,600 English-language news sites "
           "(Media Cloud), averaged over 7 days and compared with its median since 2015. A wave is a stretch "
           "of at least 5 days at 2.5× its normal level for the past year. Other news moves prices at the same "
           f"time{m['overlap_example']}, so these moves aren't caused by one storyline alone.",
           "How storylines work")


def timeline(kind, key, story, cov, waves, latest, prices, name) -> None:
    """Prices on top, the storyline's coverage below, waves shaded on both."""
    st.markdown(f"**{name} and coverage over time**")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.05)
    since = cov.index[0]
    price = prices[prices.index >= since]
    fig.add_trace(go.Scatter(x=price.index, y=price.values, mode="lines", name=name,
                             line=dict(color="#1d1d1b", width=1.3),
                             hovertemplate="%{x|%b %-d, %Y}: $%{y:.2f}<extra></extra>"), row=1, col=1)
    level = (cov["smooth"] / cov["long_run"]).dropna()
    fig.add_trace(go.Scatter(x=level.index, y=level.values, mode="lines", name="Coverage",
                             line=dict(color=story["color"], width=1.2), fill="tozeroy",
                             fillcolor=ui.rgba(story["color"], 0.25),
                             hovertemplate="%{x|%b %-d, %Y}: %{y:.1f}× normal<extra></extra>"), row=2, col=1)
    for _, w in waves.iterrows():
        fig.add_vrect(x0=w["start"], x1=w["end"], fillcolor=ui.rgba(story["color"], 0.12), line_width=0,
                      layer="below")
    start = max(since, latest["start"] - pd.DateOffset(years=2))
    fig.update_xaxes(range=[start, cov.index[-1] + pd.Timedelta(days=10)], gridcolor=ui.GRID)
    fig.update_xaxes(rangeselector=ui.range_buttons([1, 3], "Since 2015"), row=1, col=1)
    fig.update_yaxes(title_text=f"{name} ($)", tickprefix="$", row=1, col=1, gridcolor=ui.GRID)
    fig.update_yaxes(title_text="× normal", row=2, col=1, gridcolor=ui.GRID, rangemode="tozero")
    fig.update_layout(height=470, margin=dict(l=8, r=8, t=36, b=8), showlegend=False, hovermode="x unified",
                      hoverlabel=dict(bgcolor="white", bordercolor="#e1e0d9", font_color="#1d1d1b"))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"{kind}_story_chart_{key}")
    ui.tip("Shaded bands are the storyline's waves. The lower chart is its coverage compared with normal "
           "(1× = a typical day since 2015).", "How to read this")


def turning_points(key, cov, wave, prices, archive, stories, name) -> None:
    st.markdown(f"**Turning points in the {sl.wave_name(wave)}**")
    rows = []
    for day in sl.turning_points(cov, wave):
        h = sl.top_headline(archive, key, day, stories)
        x = cov.loc[day, "share"] / cov["long_run"].iloc[0]
        before = prices[prices.index < day]
        after = prices[prices.index >= day]
        week = ((after.iloc[min(5, len(after) - 1)] / before.iloc[-1] - 1) * 100
                if len(before) and len(after) > 1 else None)
        move = f" · {name} <b>{week:+.1f}%</b> the next week" if week is not None else ""
        if h is not None:
            title = html.escape(ui.headline_case(str(h["headline"])))
            link = (f'<a href="{html.escape(str(h["url"]))}" target="_blank" rel="noopener">{title}</a>'
                    if isinstance(h["url"], str) and h["url"] else f'<span class="flash-title">{title}</span>')
        else:
            link = "<span class='flash-title'>Peak news day (no saved headline)</span>"
        rows.append(f'<div class="headline">{link}<div class="meta"><span class="publisher">{ui.day(day)}</span>'
                    f' · coverage {x:.0f}× normal{move}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    ui.tip("The wave's busiest news days (at least 10 days apart), each with the saved headline that best "
           "stands for the story that day, where we have one.", "How these are picked")


def compare_waves(kind, story, major, latest, prices, name) -> None:
    if len(major) < 2:
        return
    st.write("")
    st.markdown("**This wave against past ones**")
    fig = go.Figure()
    rows = []
    for _, w in major.sort_values("start").iterrows():
        path = sl.brent_path(prices, w["start"])
        is_latest = w["start"] == latest["start"]
        wave = sl.wave_name(w)
        fig.add_trace(go.Scatter(
            x=list(range(len(path))), y=path.values, mode="lines", name=wave,
            line=dict(color=story["color"] if is_latest else "#9a988f", width=3 if is_latest else 1.3),
            opacity=1 if is_latest else 0.8, hovertemplate=f"{wave}, day %{{x}}: %{{y:+.1f}}%<extra></extra>"))
        mv = sl.wave_moves(prices, w)
        rows.append({"Wave": wave + (" (latest)" if is_latest else ""),
                     "Dates": f"{ui.day(w['start'])} – {ui.day(w['end'])}",
                     "Peak coverage": w["peak_x"], "1 week": mv["week"], "1 month": mv["month"],
                     "3 months": mv["quarter"]})
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    ui.base_layout(fig, 380, hovermode="closest", yaxis_ticksuffix="%",
                   xaxis_title="Trading days after the wave began", yaxis_title=f"{name} % change")
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"{kind}_story_compare")
    st.dataframe(pd.DataFrame(rows[::-1]), width="stretch", hide_index=True, column_config={
        "Peak coverage": st.column_config.NumberColumn(format="%.0f×"),
        "1 week": st.column_config.NumberColumn(format="%+.1f%%"),
        "1 month": st.column_config.NumberColumn(format="%+.1f%%"),
        "3 months": st.column_config.NumberColumn(format="%+.1f%%"),
    })
    ui.tip(f"Each line follows {name} from the day a wave began, for up to 6 months. The storyline's colour is "
           "the latest wave; grey lines are past ones (hover to see which). Past waves show the range of what "
           "happened before, not a forecast.", "How to read this")
