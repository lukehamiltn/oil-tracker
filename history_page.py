"""
The Event history page: one long price chart with every past event on it -
news spikes, OPEC+ decisions, Fed rate changes and big EIA surprises - so
visitors can see the actual history, not just averages. Click any dot to
see what happened that day, how every market moved after it, and what
usually happened after events like it.
"""

import html
import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import fed_events as fed
import inventory_events as inv
import markets as mk
import market_news as mn
import news_page
import ui

# Each kind of event: label, marker shape, and the symbol shown in the menu
KINDS = {
    "news": ("News spikes", "circle", "●"),
    "opec": ("OPEC+ decisions", "diamond", "◆"),
    "fed": ("Fed rate changes", "square", "■"),
    "inventory": ("Big EIA surprises", "triangle-up", "▲"),
}
BIG_SURPRISES = ["big_draw", "big_build"]    # only the largest fifth each way
# Headlines to look for in the news archive on the day of each kind of event
SEARCHES = {"opec": "OPEC", "fed": 'Fed OR "Federal Reserve" OR "interest rate"',
            "inventory": 'inventories OR stockpiles OR "crude stocks" OR EIA'}


def all_events(data: dict) -> pd.DataFrame:
    """Every event of every kind in one table: what, when, and its colour."""
    sets = data["events"]
    parts = []
    news = sets["news"]
    parts.append(pd.DataFrame({
        "kind": "news", "date": news["date"], "category": news["topic"],
        "title": news["topic"].map(news_page.LABELS),
        "detail": [h if isinstance(h, str) and h else d
                   for h, d in zip(news["headline"], news["description"])],
        "color": news["topic"].map(news_page.COLORS)}))
    opec = sets["opec"]
    parts.append(pd.DataFrame({
        "kind": "opec", "date": opec["date"], "category": opec["decision"],
        "title": "OPEC+: " + opec["decision"].map(es.LABELS),
        "detail": opec["description"], "color": opec["decision"].map(es.COLORS)}))
    fd = sets["fed"]
    parts.append(pd.DataFrame({
        "kind": "fed", "date": fd["date"], "category": fd["decision"],
        "title": "Fed: " + fd["decision"].map(fed.LABELS),
        "detail": fd["description"], "color": fd["decision"].map(fed.COLORS)}))
    stocks = sets["inventory"]
    stocks = stocks[stocks["category"].isin(BIG_SURPRISES)]
    parts.append(pd.DataFrame({
        "kind": "inventory", "date": stocks["date"], "category": stocks["category"],
        "title": "EIA: " + stocks["category"].map(inv.LABELS),
        "detail": stocks["description"], "color": stocks["category"].map(inv.COLORS)}))
    events = pd.concat(parts, ignore_index=True)
    events["date"] = pd.to_datetime(events["date"])
    return events.sort_values("date").reset_index(drop=True)


def with_reactions(events: pd.DataFrame, data: dict, market: str) -> pd.DataFrame:
    """Add each event's 1-day / 1-week / 1-month move in `market` (empty for
    events too recent to have a full month of prices after them)."""
    pct = ["day_1_pct", "day_5_pct", "day_20_pct"]
    out = []
    for kind, group in events.groupby("kind"):
        results = data["react"][kind][market][0]
        if results.empty:
            out.append(group.assign(**{c: float("nan") for c in pct}))
            continue
        cat_col = "topic" if kind == "news" else ("category" if kind == "inventory"
                                                  else "decision")
        moves = results[["date", cat_col] + pct].rename(columns={cat_col: "category"})
        moves = moves.drop_duplicates(["date", "category"])
        out.append(group.merge(moves, on=["date", "category"], how="left"))
    return pd.concat(out).sort_values("date").reset_index(drop=True)


def hover_text(row, short: str) -> str:
    detail = "<br>".join(textwrap.wrap(html.escape(str(row["detail"])[:160]), 60))
    move = (f"{short} a week later: <b>{row['day_5_pct']:+.1f}%</b>"
            if pd.notna(row["day_5_pct"]) else f"{short} a week later: not known yet")
    return f"<b>{html.escape(row['title'])}</b> · {row['date']:%b %d, %Y}<br>{detail}<br>{move}"


def timeline_chart(prices: pd.Series, events: pd.DataFrame, market: str, chosen=None):
    label, short, line_color = mk.MARKETS[market]
    fig = go.Figure()
    # The price line itself can't be hovered or clicked, so the dots are easy to hit
    fig.add_trace(go.Scatter(
        x=prices.index, y=prices.values, mode="lines", name=label,
        line=dict(color="#52514e", width=1.3), hoverinfo="skip"))
    # Put each dot on the price line, on the event day (or the last trading day before)
    events = events.assign(y=prices.reindex(events["date"], method="ffill").values)
    events = events.dropna(subset=["y"])
    for kind, (name, symbol, _) in KINDS.items():
        group = events[events["kind"] == kind]
        if group.empty:
            continue
        fig.add_trace(go.Scatter(
            x=group["date"], y=group["y"], mode="markers", name=name,
            marker=dict(symbol=symbol, size=11 if kind != "news" else 9,
                        color=group["color"], line=dict(color="#ffffff", width=1.2)),
            customdata=group.index.to_numpy()[:, None],
            hovertext=[hover_text(r, short) for _, r in group.iterrows()],
            hovertemplate="%{hovertext}<extra></extra>",
            unselected=dict(marker=dict(opacity=1))))     # clicking doesn't dim the rest
    if chosen is not None and chosen.name in events.index:
        y = events.loc[chosen.name, "y"]
        fig.add_trace(go.Scatter(
            x=[chosen["date"]], y=[y], mode="markers", hoverinfo="skip", showlegend=False,
            marker=dict(size=24, color="rgba(0,0,0,0)", line=dict(color="#1d1d1b", width=2))))
    end = prices.index[-1]
    start = end - pd.DateOffset(years=5)
    visible = prices[start:]
    low, high = visible.min(), visible.max()
    ui.base_layout(fig, 480, hovermode="closest", showlegend=False,
                   yaxis_title=f"{label} ({'index' if market == 'DOLLAR' else 'USD'})",
                   dragmode="pan")
    fig.update_xaxes(range=[start, end + pd.Timedelta(days=20)],
                     rangeselector=dict(buttons=[
                         dict(count=1, label="1 year", step="year", stepmode="backward"),
                         dict(count=5, label="5 years", step="year", stepmode="backward"),
                         dict(count=10, label="10 years", step="year", stepmode="backward"),
                         dict(step="all", label="All")], x=0, y=1.08,
                         bgcolor="#f3f2ee", activecolor="#e1e0d9", font=dict(size=12)))
    # Fit the price axis to the years on screen (double-click the chart to refit)
    pad = (high - low) * 0.08
    fig.update_yaxes(range=[low - pad, high + pad])
    return fig, events


def day_headlines(archive: pd.DataFrame, event) -> pd.DataFrame:
    """Archive headlines from the day before to the day after the event
    (weekend meetings are often reported on the Monday)."""
    if archive.empty:
        return archive
    day = event["date"].normalize()
    window = archive[(archive["day"] >= day - pd.Timedelta(days=1))
                     & (archive["day"] <= day + pd.Timedelta(days=1))]
    if window.empty:
        return window
    if event["kind"] == "news":
        hits = window[mn.topic_match(window, {"topic": event["category"]})]
    else:
        hits = window[mn.search_mask(window, SEARCHES[event["kind"]])]
    return hits.sort_values("time", ascending=False).head(5)


def reaction_table(data: dict, event) -> None:
    """How every market moved after this one event."""
    rows = {}
    for key, (results, _) in data["react"][event["kind"]].items():
        if results.empty:
            continue
        cat_col = "topic" if event["kind"] == "news" else (
            "category" if event["kind"] == "inventory" else "decision")
        hit = results[(results["date"] == event["date"]) & (results[cat_col] == event["category"])]
        if len(hit):
            rows[key] = hit.iloc[0]
    if not rows:
        st.caption("Too recent: the market reaction isn't known yet.")
        return
    shown = pd.DataFrame(index=[mk.MARKETS[k][0] for k in rows])
    shades = pd.DataFrame(index=shown.index)
    for h, name in zip(es.HORIZONS, ["1 day", "1 week", "1 month"]):
        values = [rows[k][f"day_{h}_pct"] for k in rows]
        shown[name] = [f"{v:+.1f}%" for v in values]
        shades[name] = [ui._shade(v, data["typical"][h][k]) for v, k in zip(values, rows)]
    st.dataframe(shown.style.apply(lambda _: shades, axis=None), width="stretch",
                 key="history_reaction")
    st.caption("Colour strength = how big the move was compared with that market's "
               "ordinary moves.")


def path_chart(data: dict, event, market: str) -> None:
    paths = data["react"][event["kind"]][market][1]
    path = paths.get(event["date"])
    if path is None:
        return
    short = mk.MARKETS[market][1]
    fig = go.Figure(go.Scatter(x=path.index, y=path.values, mode="lines+markers",
                               line=dict(color=event["color"], width=3), marker=dict(size=4),
                               hovertemplate="Day %{x}: %{y:+.1f}%<extra></extra>"))
    ui.style_event_chart(fig, f"% change in {short}", 300)
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, width="stretch", key="history_path")


def similar_summary(data: dict, event, market: str) -> None:
    """What usually happened after events of the same kind - with the
    'is this real?' badge, so one dramatic case isn't mistaken for a rule."""
    results = data["react"][event["kind"]][market][0]
    if results.empty:
        return
    cat_col = "topic" if event["kind"] == "news" else (
        "category" if event["kind"] == "inventory" else "decision")
    others = results[(results[cat_col] == event["category"]) & (results["date"] != event["date"])]
    week = others["day_5_pct"].dropna()
    if week.empty:
        return
    short = mk.MARKETS[market][1]
    sig = data["sig"]
    p = sig.p_value(market, 5, week)
    verdict = sig.verdict(p, len(week))
    name = event["title"].split(": ")[-1]
    st.html(ui.CARD_CSS)
    st.markdown(
        f"<div class='eyebrow' style='margin-top:0.6rem'>Every other “{html.escape(name)}”</div>"
        f"<div class='past'>{len(week)} other times: {short} averaged "
        f"<b>{week.mean():+.1f}%</b> a week later and rose {(week > 0).mean():.0%} of the time.</div>"
        + ui.verdict_badge(verdict, ui.verdict_tip(verdict, p, len(week), f"week for {short}")),
        unsafe_allow_html=True)


def _event_id(custom) -> int | None:
    """The event number stored on a clicked dot (Plotly may hand it back as a
    number, a list or a dict, depending on version)."""
    while isinstance(custom, (list, tuple, dict)) and custom:
        custom = next(iter(custom.values())) if isinstance(custom, dict) else custom[0]
    try:
        return int(custom)
    except (TypeError, ValueError):
        return None


@st.fragment
def render(data: dict) -> None:
    ui.eyebrow("Event history")
    st.subheader("Every past oil event on one chart", anchor=False)
    st.caption("News spikes, OPEC+ decisions, Fed rate changes and the biggest EIA "
               "inventory surprises, placed on the price line. Hover a dot for a summary; "
               "click it to see what happened next. Drag to move through time.")

    left, right = st.columns([3, 2], vertical_alignment="bottom")
    kinds = left.pills("Show", list(KINDS), selection_mode="multi", default=["news", "opec", "fed"],
                       key="history_kinds",
                       format_func=lambda k: f"{KINDS[k][2]} {KINDS[k][0]}") or []
    with right:
        market = ui.market_picker("history_market", data["markets"], label="Price line")

    events = all_events(data)
    events = events[events["kind"].isin(kinds)]
    if events.empty:
        st.info("Pick at least one kind of event to show.")
        return
    events = with_reactions(events, data, market)
    # Which event to show: the one just clicked (the click arrives before the
    # chart is redrawn), else the last one clicked, else the latest event
    # whose market reaction is already known. Remembered by date + kind +
    # category, which stay the same when switching markets.
    clicked = st.session_state.get("history_chart") or {}
    points = clicked.get("selection", {}).get("points", [])
    idx = _event_id(points[0].get("customdata")) if points else None
    if idx is not None and st.session_state.get("history_click") != idx:
        st.session_state["history_click"] = idx
        if idx in events.index:
            row = events.loc[idx]
            st.session_state["history_pick"] = (row["date"], row["kind"], row["category"])
    pick = st.session_state.get("history_pick")
    match = (events[(events["date"] == pick[0]) & (events["kind"] == pick[1])
                    & (events["category"] == pick[2])] if pick else events.iloc[0:0])
    known = events[events["day_1_pct"].notna()]
    event = (match.iloc[0] if len(match) else
             known.iloc[-1] if len(known) else events.iloc[-1])

    fig, plotted = timeline_chart(data["markets"][market], events, market, event)
    st.plotly_chart(fig, width="stretch", key="history_chart", on_select="rerun",
                    selection_mode="points",
                    config={"scrollZoom": False, "displayModeBar": False})

    # ---- The chosen event ---------------------------------------------------
    st.write("")
    with st.container(border=True):
        info, chart = st.columns([2, 3], gap="large")
        with info:
            ui.eyebrow(f"{KINDS[event['kind']][0]} · {event['date']:%A %b %d, %Y}")
            st.markdown(ui.chip(html.escape(event["title"]), event["color"]),
                        unsafe_allow_html=True)
            st.markdown(html.escape(str(event["detail"])))
            heads = day_headlines(data["archive"], event)
            if len(heads):
                st.markdown("<div class='eyebrow' style='margin-top:0.6rem'>Headlines that day</div>",
                            unsafe_allow_html=True)
                news_page.headline_list(heads)
            similar_summary(data, event, market)
        with chart:
            short = mk.MARKETS[market][1]
            st.markdown(f"**{short} around this event**")
            path_chart(data, event, market)
            st.markdown("**Every market after this event**")
            reaction_table(data, event)
    if not pick:
        st.caption("Showing the latest event with a known result. Click any dot on the "
                   "chart to see another.")
