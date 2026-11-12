"""The Storylines view (News tab): big stories that come back in waves, and
what Brent did during each wave. Calculations are in storylines.py."""

import html

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import live_prices
import storylines as sl
import ui


@st.cache_data(ttl=30 * 60, show_spinner=False)
def _coverage(version: float) -> pd.DataFrame:
    return sl.load()


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _brent(_official: pd.Series, last_day: str) -> pd.Series:
    """Official Brent, carried to today with scaled futures (see live_prices.extend)."""
    try:
        return live_prices.extend(_official, "BRENT")[0]
    except Exception:
        return _official


def summary_of(table: pd.DataFrame, key: str, brent: pd.Series) -> dict | None:
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
        "moves": sl.wave_moves(brent, latest),
    }


def render(data: dict) -> None:
    path = sl.PATH
    table = _coverage(path.stat().st_mtime if path.exists() else 0)
    if table.empty:
        st.info("Storyline data isn't available yet. It's refreshed every 3 hours.")
        return
    official = data["markets"]["BRENT"]
    brent = _brent(official, str(official.index[-1]))
    keys = [k for k in sl.STORYLINES if k in set(table["storyline"])]
    summaries = {k: summary_of(table, k, brent) for k in keys}
    keys = [k for k in keys if summaries[k] is not None]
    # Busiest storyline right now first
    keys.sort(key=lambda k: summaries[k]["now_x"], reverse=True)

    st.subheader("Storylines", anchor=False)
    st.caption("Big stories that run for months and come back in waves. For each one: how "
               "much worldwide news it gets, when its waves came, and what Brent did during "
               "them.")
    pick = st.session_state.get("storyline")
    if pick not in keys:
        st.session_state["storyline"] = keys[0]
    key = st.pills("Storyline", keys, key="storyline", label_visibility="collapsed",
                   format_func=lambda k: sl.STORYLINES[k]["label"]) or keys[0]
    story, s = sl.STORYLINES[key], summaries[key]
    latest, cov, moves = s["latest"], s["cov"], s["moves"]

    st.markdown(f"<div class='dialog-topic'>{story['label']}</div>"
                f"<div class='why-rank' style='margin-bottom:0.8rem'>{story['summary']}</div>",
                unsafe_allow_html=True)

    # Other storylines' big waves running at the same time (they move oil too)
    overlaps = []
    for other in keys:
        if other == key:
            continue
        for _, w in summaries[other]["major"].iterrows():
            shared = (min(w["end"], latest["end"]) - max(w["start"], latest["start"])).days
            if shared >= 30:
                overlaps.append(sl.STORYLINES[other]["label"])
                break
    brent_note = (f"low {moves['low']:+.0f}%, high {moves['high']:+.0f}% in its first 6 months")
    if overlaps:
        brent_note = f"also during: {', '.join(overlaps)} · " + brent_note

    end_text = "now" if s["ongoing"] else ui.day(latest["end"])
    peak_x = latest["peak_x"]
    level = ("far above normal" if s["now_x"] >= 5 else "above normal" if s["now_x"] >= 2
             else "close to normal")
    ui.kpi_row([
        ("Coverage now", f"{s['now_x']:.1f}× normal",
         f"{level} · last 7 days vs its median since 2015", None),
        ("Latest wave", "Ongoing" if s["ongoing"] else "Ended",
         f"{ui.day(latest['start'])} – {end_text} · peak {peak_x:.0f}× normal "
         f"on {ui.day(latest['peak'])}", None),
        ("Brent during this wave", f"{moves['whole']:+.0f}%", brent_note, None),
        ("Waves since 2015", f"{len(s['waves'])}",
         f"{len(s['major'])} big ones compared below", None),
    ])

    timeline(key, story, cov, s["waves"], s["latest"], brent)
    turning_points(key, cov, latest, brent, data)
    compare_waves(story, s["major"], latest, brent)
    ui.tip("Coverage is the storyline's share of all stories in about 1,600 English-language "
           "news sites (Media Cloud), averaged over 7 days and compared with its median since "
           "2015. A wave is a stretch of at least 5 days at 2.5× its normal level for the past "
           "year. Other news moves oil at the same time (the 2025–26 Venezuela wave overlaps "
           "the Iran war, for example), so these moves aren't caused by one storyline alone.",
           "How storylines work")


def timeline(key, story, cov, waves, latest, brent) -> None:
    """Brent on top, the storyline's coverage below, waves shaded on both."""
    st.markdown("**Brent and coverage over time**")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38],
                        vertical_spacing=0.05)
    since = cov.index[0]
    price = brent[brent.index >= since]
    fig.add_trace(go.Scatter(x=price.index, y=price.values, mode="lines", name="Brent",
                             line=dict(color="#1d1d1b", width=1.3),
                             hovertemplate="%{x|%b %-d, %Y}: $%{y:.2f}<extra></extra>"),
                  row=1, col=1)
    level = (cov["smooth"] / cov["long_run"]).dropna()
    fig.add_trace(go.Scatter(x=level.index, y=level.values, mode="lines", name="Coverage",
                             line=dict(color=story["color"], width=1.2), fill="tozeroy",
                             fillcolor=ui.rgba(story["color"], 0.25),
                             hovertemplate="%{x|%b %-d, %Y}: %{y:.1f}× normal<extra></extra>"),
                  row=2, col=1)
    for _, w in waves.iterrows():
        fig.add_vrect(x0=w["start"], x1=w["end"], fillcolor=ui.rgba(story["color"], 0.12),
                      line_width=0, layer="below")
    start = max(since, latest["start"] - pd.DateOffset(years=2))
    fig.update_xaxes(range=[start, cov.index[-1] + pd.Timedelta(days=10)], gridcolor=ui.GRID)
    fig.update_xaxes(rangeselector=dict(buttons=[
        dict(count=1, label="1 year", step="year", stepmode="backward"),
        dict(count=3, label="3 years", step="year", stepmode="backward"),
        dict(step="all", label="Since 2015")], x=1, xanchor="right", y=1.02, yanchor="bottom",
        bgcolor="#ffffff", activecolor="#dbe5f1", bordercolor="#e1e0d9", borderwidth=1,
        font=dict(size=12)), row=1, col=1)
    fig.update_yaxes(title_text="Brent ($)", tickprefix="$", row=1, col=1, gridcolor=ui.GRID)
    fig.update_yaxes(title_text="× normal", row=2, col=1, gridcolor=ui.GRID, rangemode="tozero")
    fig.update_layout(height=470, margin=dict(l=8, r=8, t=36, b=8), showlegend=False,
                      hovermode="x unified",
                      hoverlabel=dict(bgcolor="white", bordercolor="#e1e0d9",
                                      font_color="#1d1d1b"))
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key=f"story_chart_{key}")
    ui.tip("Shaded bands are the storyline's waves. The lower chart is its coverage compared "
           "with normal (1× = a typical day since 2015).", "How to read this")


def turning_points(key, cov, wave, brent, data) -> None:
    st.markdown(f"**Turning points in the {sl.wave_name(wave)}**")
    rows = []
    for day in sl.turning_points(cov, wave):
        h = sl.top_headline(data["archive"], key, day)
        x = cov.loc[day, "share"] / cov["long_run"].iloc[0]
        before = brent[brent.index < day]
        after = brent[brent.index >= day]
        week = ((after.iloc[min(5, len(after) - 1)] / before.iloc[-1] - 1) * 100
                if len(before) and len(after) > 1 else None)
        move = (f" · Brent <b>{week:+.1f}%</b> the next week" if week is not None else "")
        if h is not None:
            title = html.escape(ui.headline_case(str(h["headline"])))
            link = (f'<a href="{html.escape(str(h["url"]))}" target="_blank" rel="noopener">'
                    f'{title}</a>' if isinstance(h["url"], str) and h["url"] else
                    f'<span class="flash-title">{title}</span>')
        else:
            link = "<span class='flash-title'>No saved headline for this day</span>"
        rows.append(f'<div class="headline">{link}<div class="meta">'
                    f'<span class="publisher">{ui.day(day)}</span> · coverage {x:.0f}× normal'
                    f'{move}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    ui.tip("The wave's busiest news days (at least 10 days apart), each with the saved "
           "headline that best stands for the story that day.", "How these are picked")


def compare_waves(story, major, latest, brent) -> None:
    if len(major) < 2:
        return
    st.write("")
    st.markdown("**This wave against past ones**")
    fig = go.Figure()
    rows = []
    for _, w in major.sort_values("start").iterrows():
        path = sl.brent_path(brent, w["start"])
        is_latest = w["start"] == latest["start"]
        name = sl.wave_name(w)
        fig.add_trace(go.Scatter(
            x=list(range(len(path))), y=path.values, mode="lines", name=name,
            line=dict(color=story["color"] if is_latest else "#9a988f",
                      width=3 if is_latest else 1.3),
            opacity=1 if is_latest else 0.8,
            hovertemplate=f"{name}, day %{{x}}: %{{y:+.1f}}%<extra></extra>"))
        m = sl.wave_moves(brent, w)
        rows.append({"Wave": name + (" (latest)" if is_latest else ""),
                     "Dates": f"{ui.day(w['start'])} – {ui.day(w['end'])}",
                     "Peak coverage": w["peak_x"], "1 week": m["week"], "1 month": m["month"],
                     "3 months": m["quarter"]})
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    ui.base_layout(fig, 380, hovermode="closest", yaxis_ticksuffix="%",
                   xaxis_title="Trading days after the wave began",
                   yaxis_title="Brent % change")
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="story_compare")
    st.dataframe(pd.DataFrame(rows[::-1]), width="stretch", hide_index=True, column_config={
        "Peak coverage": st.column_config.NumberColumn(format="%.0f×"),
        "1 week": st.column_config.NumberColumn(format="%+.1f%%"),
        "1 month": st.column_config.NumberColumn(format="%+.1f%%"),
        "3 months": st.column_config.NumberColumn(format="%+.1f%%"),
    })
    ui.tip("Each line follows Brent from the day a wave began, for up to 6 months. The "
           "storyline's colour is the latest wave; grey lines are past ones (hover to see "
           "which). Past waves "
           "show the range of what happened before, not a forecast.", "How to read this")
