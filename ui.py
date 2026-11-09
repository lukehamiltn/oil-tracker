"""
Shared look and building blocks for every page of the website:
the page styling, chart styling, and the event-study sections reused by the
News, EIA, OPEC+ and Fed pages.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es
import markets as mk

HORIZON_NAMES = {1: "1 day", 5: "1 week (5 trading days)", 20: "1 month (20 trading days)"}
PCT = "%+.1f%%"
MUTED = "#898781"
GRID = "#ecebe6"

HORIZON_COLUMNS = {
    "day_1_pct": st.column_config.NumberColumn("1 day", format=PCT),
    "day_5_pct": st.column_config.NumberColumn("1 week", format=PCT),
    "day_20_pct": st.column_config.NumberColumn("1 month", format=PCT),
}

CSS = """
<style>
/* No link icons next to headings (they only scroll the page to the heading) */
[data-testid="stHeaderActionElements"] { display: none !important; }
/* Comfortable reading width on big screens */
.block-container { max-width: 1240px; padding-top: 2.2rem; padding-bottom: 4rem; }
/* Hero */
.hero-title { font-size: 2.1rem; font-weight: 700; letter-spacing: -0.02em; margin: 0; color: #1d1d1b; }
.hero-sub { font-size: 1.05rem; color: #52514e; margin: 0.25rem 0 0 0; }
/* Tabs: a little more room and weight */
.stTabs [data-baseweb="tab-list"] { gap: 0.4rem; border-bottom: 1px solid #e1e0d9; }
.stTabs [data-baseweb="tab"] { padding: 0.55rem 0.9rem; font-weight: 500; }
/* Small grey label above a section */
.eyebrow { text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.72rem;
           font-weight: 600; color: #898781; margin-bottom: 0.15rem; }
/* Headline list */
.headline { padding: 0.55rem 0; border-bottom: 1px solid #ecebe6; }
.headline a { color: #1d1d1b; text-decoration: none; font-weight: 500; }
.headline a:hover { color: #256abf; text-decoration: underline; }
.headline .meta { color: #898781; font-size: 0.8rem; margin-top: 0.1rem; }
.chip { display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 0.08rem 0.5rem;
        border-radius: 999px; margin-right: 0.3rem; color: #ffffff; }
.footer { color: #898781; font-size: 0.8rem; margin-top: 3rem; padding-top: 1rem;
          border-top: 1px solid #ecebe6; }
</style>
"""


def apply_styles() -> None:
    st.html(CSS)


def eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{text}</div>', unsafe_allow_html=True)


def chip(text: str, color: str) -> str:
    return f'<span class="chip" style="background:{color}">{text}</span>'


# ---- Topic cards: "how loud is it now" vs "does history say it matters" ----
# The two answers get different looks on purpose: coverage is shown as a
# temperature (coloured card edge, dot, number and gauge), the pattern check
# as an outlined badge with signal-strength bars.

CARD_CSS = """
<style>
.status { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
          display: flex; align-items: center; gap: 0.4rem; }
.status .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status .dot.pulse { animation: pulse 1.6s ease-out infinite; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(227,73,72,0.55); }
                   100% { box-shadow: 0 0 0 7px rgba(227,73,72,0); } }
.heat-num { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
.heat-unit { color: #898781; font-size: 0.85rem; }
.meter { position: relative; height: 6px; background: #ecebe6; border-radius: 3px; margin: 0.3rem 0 0.15rem; }
.meter .fill { height: 100%; border-radius: 3px; }
.meter .tick { position: absolute; top: -3px; width: 2px; height: 12px; background: #52514e; border-radius: 1px; }
.meter-label { font-size: 0.68rem; color: #898781; position: relative; height: 0.9rem; }
.card-rule { border-top: 1px dashed #e1e0d9; margin: 0.2rem 0 0.1rem; }
/* Titles and the history line always take two lines, so every card has
   its parts at the same height whether its text wraps or not */
.card-title { font-weight: 600; line-height: 1.35; margin: 0.35rem 0 0.1rem; height: 2.7em;
              display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.past { font-size: 0.85rem; color: #52514e; line-height: 1.45; min-height: 2.9em; }
.verdict { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.74rem; font-weight: 600;
           padding: 0.12rem 0.55rem 0.12rem 0.45rem; border: 1.5px solid; border-radius: 6px;
           background: #ffffff; margin-top: 0.35rem; }
/* Hover explanation above the pattern badge */
.verdict-wrap { position: relative; display: inline-block; cursor: help; }
.verdict-wrap .tip { visibility: hidden; opacity: 0; transition: opacity 0.15s;
    position: absolute; bottom: calc(100% + 8px); left: 0; width: 235px; z-index: 20;
    background: #1d1d1b; color: #ffffff; font-size: 0.75rem; font-weight: 400; line-height: 1.45;
    padding: 0.55rem 0.7rem; border-radius: 7px; box-shadow: 0 4px 14px rgba(0,0,0,0.18); }
.verdict-wrap .tip::after { content: ""; position: absolute; top: 100%; left: 18px;
    border: 6px solid transparent; border-top-color: #1d1d1b; }
.verdict-wrap:hover .tip { visibility: visible; opacity: 1; }
</style>
"""

VERDICT_BARS = {"strong": 3, "possible": 2, "noise": 1, "few": 0}


def status_line(label: str, color: str, pulse: bool = False) -> str:
    dot = f'<span class="dot{" pulse" if pulse else ""}" style="background:{color}"></span>'
    return f'<div class="status" style="color:{color}">{dot}{label}</div>'


def heat_gauge(heat: float, color: str, top: float = 3.0) -> str:
    """A bar filled up to today's coverage, with a tick where 'normal' (1×) is."""
    fill, tick = min(heat / top, 1) * 100, 100 / top
    return (f'<div class="meter"><div class="fill" style="width:{max(fill, 2):.0f}%;'
            f'background:{color}"></div><span class="tick" style="left:{tick:.1f}%"></span></div>'
            f'<div class="meter-label"><span style="position:absolute;left:{tick:.1f}%;'
            f'transform:translateX(-50%)">normal</span>'
            f'<span style="position:absolute;right:0">{top:.0f}×+</span></div>')


def verdict_tip(verdict: str, p: float, n: int, what: str = "week") -> str:
    """Plain-words explanation of a pattern verdict, with this case's numbers."""
    share = "under 1%" if p < 0.01 else f"{p:.0%}"
    sets = f"Random sets of {n} ordinary days"
    return {
        "strong": f"<b>Very likely real.</b> {sets} (picked thousands of times) moved this far "
                  f"from normal only {share} of the time, so luck is an unlikely explanation.",
        "possible": f"<b>Maybe real.</b> {sets} moved this far from normal {share} of the time. "
                    "That's unusual, but not rare enough to rule out luck.",
        "noise": f"<b>Could just be luck.</b> {sets} moved this far from normal {share} of the "
                 f"time, so the {what} after these events isn't clearly different from any other.",
        "few": "<b>Too few events.</b> With fewer than 5 past cases we can't tell a pattern "
               "from luck.",
    }[verdict]


def verdict_badge(verdict: str, tip: str | None = None) -> str:
    """Outlined badge with 0–3 signal bars: how sure we are the pattern is real.
    With tip, hovering the badge shows that explanation."""
    text, color = mk.VERDICTS[verdict]
    level = VERDICT_BARS[verdict]
    bars = "".join(
        f'<rect x="{i * 5}" y="{8 - 3 * i}" width="3.5" height="{4 + 3 * i}" rx="1" '
        f'fill="{color if i < level else "#d6d4cc"}"/>' for i in range(3))
    badge = (f'<span class="verdict" style="color:{color};border-color:{color}">'
             f'<svg width="14" height="12" viewBox="0 0 14 12">{bars}</svg>{text}</span>')
    if tip:
        badge = f'<span class="verdict-wrap">{badge}<span class="tip">{tip}</span></span>'
    return badge


def topic_picker(label: str, options: list, labels: dict, colors: dict, key: str,
                 default=None, none_text: str = "",
                 clear_text: str | None = None) -> str | None:
    """A compact button that opens a panel of chips, each in its topic's own
    colour (Streamlit menus can only show plain text, so the chips are
    coloured here with CSS, by their position in the group). The current
    choice is shown as a chip beside the button; with clear_text, a small
    button next to it removes the choice again."""
    rules = []
    for i, option in enumerate(options):
        c = colors[option]
        chip_css = f'.st-key-{key} button[data-variant="pills"]:nth-child({i + 1})'
        rules.append(
            f'{chip_css} {{ background:{c} !important; border-color:{c} !important; opacity:.6; }}'
            f'{chip_css}, {chip_css} * {{ color:#fff !important; }}'
            f'{chip_css}:hover {{ opacity:.85; }}'
            f'{chip_css}[aria-checked="true"] {{ opacity:1; '
            f'box-shadow:0 0 0 2px #fff, 0 0 0 4px {c}; }}')
    st.html("<style>" + "".join(rules) + "</style>")
    left, right = st.columns([1, 3], vertical_alignment="center")
    with left.popover(label, width="stretch"):
        picked = st.pills(label, options, format_func=labels.get, key=key,
                          default=default, label_visibility="collapsed")
    chosen = picked or default
    if clear_text and picked:
        # The chosen chip is itself a button: hovering shows an X badge in its
        # corner, and clicking it removes the choice.
        c = colors[chosen]
        css = f".st-key-{key}_clear button"
        st.html(f"""<style>
{css} {{ background:{c} !important; border:none !important; border-radius:999px !important;
        padding:0.1rem 0.6rem !important; min-height:0 !important; position:relative;
        overflow:visible !important; }}
{css} p {{ color:#fff !important; font-size:0.72rem !important; font-weight:600 !important; }}
{css}::after {{ content:"✕"; position:absolute; top:-7px; right:-7px; width:16px; height:16px;
               border-radius:50%; background:#1d1d1b; color:#fff; font-size:9px;
               line-height:16px; text-align:center; opacity:0; transition:opacity .15s; }}
{css}:hover::after, {css}:focus-visible::after {{ opacity:1; }}
.st-key-{key}_clear, .st-key-{key}_clear * {{ overflow:visible !important; }}
</style>""")

        def clear() -> None:       # runs before the redraw, so the chips reset too
            st.session_state[key] = None
        right.button(labels[chosen], key=f"{key}_clear", on_click=clear, help=clear_text)
    else:
        right.markdown(chip(labels[chosen], colors[chosen]) if chosen else
                       f'<span style="color:#898781">{none_text}</span>',
                       unsafe_allow_html=True)
    return chosen


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def base_layout(fig: go.Figure, height: int = 400, **extra) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=24, b=8),
        legend=dict(orientation="h", yanchor="top", y=-0.2, x=0, font=dict(size=12)),
        hoverlabel=dict(bgcolor="white", bordercolor="#e1e0d9", font_color="#1d1d1b"),
        **extra)
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def style_event_chart(fig: go.Figure, y_title: str, height: int = 400) -> go.Figure:
    fig.add_hline(y=0, line_color="#c3c2b7", line_width=1)
    fig.add_vline(x=0, line_color=MUTED, line_dash="dot", line_width=1,
                  annotation_text="close before the news",
                  annotation_font_size=11, annotation_font_color=MUTED)
    return base_layout(fig, height, hovermode="x unified",
                       xaxis_title="Trading days from the close before the news",
                       yaxis_title=y_title, yaxis_ticksuffix="%")


def average_path(paths: dict, dates) -> pd.Series:
    return pd.concat([paths[d] for d in dates], axis=1).mean(axis=1)


# ---------------------------------------------------------------------------
# Event-study sections (used by every event page)
# ---------------------------------------------------------------------------
@st.fragment
def comparison_section(prices, results, paths, cat_col, categories, labels, colors, key,
                       market: str = "Brent", sig=None, market_key: str = "BRENT"):
    """Average price path for every category, plus a summary table.
    (A fragment: changing its options only redraws this section.)"""
    if results.empty:
        st.info(f"No events of this kind have {market} price data yet.")
        return
    fig = go.Figure()
    for cat in categories:
        dates = results.loc[results[cat_col] == cat, "date"]
        if dates.empty:
            continue
        avg = average_path(paths, dates)
        fig.add_trace(go.Scatter(
            x=avg.index, y=avg.values, mode="lines", name=f"{labels[cat]} ({len(dates)})",
            line=dict(color=colors[cat], width=2.5), hovertemplate="%{y:+.1f}%"))
    st.plotly_chart(style_event_chart(fig, f"Average % change in {market}"), width="stretch",
                    key=f"{key}_avg_chart")

    horizon = st.segmented_control("Measure the change after", es.HORIZONS, default=1,
                                   format_func=lambda h: HORIZON_NAMES[h].split(" (")[0],
                                   key=f"{key}_horizon") or 1
    col = f"day_{horizon}_pct"
    summary = (results.groupby(cat_col)[col]
               .agg(events="count", average="mean", median="median",
                    pct_up=lambda s: (s > 0).mean() * 100, best="max", worst="min")
               .reindex(categories).dropna(how="all"))
    if sig is not None:
        verdicts = {c: sig.check(market_key, horizon, g) for c, g in results.groupby(cat_col)[col]}
        summary["pattern"] = [mk.VERDICTS[verdicts.get(c, "few")][0] for c in summary.index]
    summary.index = [labels[c] for c in summary.index]
    st.dataframe(summary, width="stretch", key=f"{key}_summary", column_config={
        "pattern": st.column_config.TextColumn(
            "Pattern?", help="Could random days have produced an average this big? "
                             "See 'How this works'."),
        "events": st.column_config.NumberColumn("Events"),
        "average": st.column_config.NumberColumn("Average", format=PCT),
        "median": st.column_config.NumberColumn("Median", format=PCT),
        "pct_up": st.column_config.NumberColumn("Times price rose", format="%.0f%%"),
        "best": st.column_config.NumberColumn("Best", format=PCT),
        "worst": st.column_config.NumberColumn("Worst", format=PCT),
    })
    st.caption(f"For comparison: at any ordinary time, {market}'s typical move over "
               f"{HORIZON_NAMES[horizon]} is about ±{es.typical_move(prices, horizon):.1f}%. "
               "**Pattern?** says how unlikely the average would be on random days: "
               "a strong pattern happens by chance less than 2% of the time.")


@st.fragment
def drilldown_section(results, paths, cat_col, categories, labels, colors,
                      table_columns, key, select_label="Category", market: str = "Brent"):
    """Pick one category: each event (or the spread, if many) + a table."""
    cat = st.selectbox(select_label, categories, format_func=lambda c: labels[c],
                       key=f"{key}_select")
    group = results[results[cat_col] == cat] if not results.empty else results
    event_paths(group, paths, colors[cat], table_columns, key, market)


def event_paths(group, paths, color, table_columns, key, market: str = "Brent") -> None:
    """Chart of the price path after each event in `group`, plus its table."""
    group = group.sort_values("date", ascending=False)
    if group.empty:
        st.caption("No events of this kind yet.")
        return
    fig = go.Figure()

    if len(group) <= 60:
        for _, event in group.iterrows():
            path = paths[event["date"]]
            fig.add_trace(go.Scatter(
                x=path.index, y=path.values, mode="lines", showlegend=False,
                line=dict(color=color, width=1), opacity=0.3,
                hovertemplate=f"<b>{event['date']:%b %d, %Y}</b><br>"
                              f"{event['description']}<br>%{{y:+.1f}}%<extra></extra>"))
        note = "Thin lines are individual events (hover to see which). Thick line = average."
    else:
        all_paths = pd.concat([paths[d] for d in group["date"]], axis=1)
        low, high = all_paths.quantile(0.25, axis=1), all_paths.quantile(0.75, axis=1)
        fig.add_trace(go.Scatter(x=high.index, y=high.values, mode="lines",
                                 line=dict(width=0), showlegend=False,
                                 hovertemplate="75th percentile: %{y:+.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=low.index, y=low.values, mode="lines",
                                 line=dict(width=0), fill="tonexty", fillcolor=color,
                                 opacity=0.2, name="Middle 50% of outcomes",
                                 hovertemplate="25th percentile: %{y:+.1f}%<extra></extra>"))
        note = ("Shaded band = where the middle half of outcomes landed. "
                "Thick line = average. A wide band means the average isn't very reliable.")

    avg = average_path(paths, group["date"])
    fig.add_trace(go.Scatter(x=avg.index, y=avg.values, mode="lines", name="Average",
                             line=dict(color=color, width=3.5),
                             hovertemplate="Average: %{y:+.1f}%<extra></extra>"))
    fig = style_event_chart(fig, f"% change in {market}")
    fig.update_layout(hovermode="closest" if len(group) <= 60 else "x unified")
    st.plotly_chart(fig, width="stretch", key=f"{key}_drill_chart")
    st.caption(note)
    st.dataframe(group[[c for c in table_columns if c in group]], width="stretch",
                 hide_index=True, key=f"{key}_events", column_config=table_columns)


# ---------------------------------------------------------------------------
# Several markets
# ---------------------------------------------------------------------------
UP, DOWN = (27, 175, 122), (227, 73, 72)    # green / red (rgb)


def market_picker(key: str, available, label: str = "Measure the reaction in") -> str:
    """A row of buttons to choose which market the charts below measure."""
    options = [k for k in mk.MARKETS if k in available]
    return st.segmented_control(label, options, default="BRENT", key=key,
                                format_func=lambda k: mk.MARKETS[k][1]) or "BRENT"


MARKS = {"strong": " ●●", "possible": " ●", "noise": "", "few": ""}
LEGEND = ("●● strong pattern (random days do this less than 2% of the time) · "
          "● possible pattern (less than 10%) · grey = could be noise, or too few events")


def _shade(value: float, typical: float, verdict: str = "strong") -> str:
    """Green for a rise, red for a fall; stronger when the move is large
    compared with that market's ordinary moves. Moves that could be noise
    are greyed out instead of coloured."""
    if pd.isna(value) or not typical:
        return ""
    if verdict in ("noise", "few"):
        return "color: #a3a29c"
    strength = min(abs(value) / typical, 2) / 2          # 0 .. 1
    r, g, b = UP if value > 0 else DOWN
    weight = "font-weight: 600; " if verdict == "strong" else ""
    return f"{weight}background-color: rgba({r},{g},{b},{0.12 + 0.5 * strength:.2f})"


def _cell(value: float, verdict: str) -> str:
    return "" if pd.isna(value) else f"{value:+.1f}%{MARKS.get(verdict, '')}"


@st.fragment
def cross_market_section(by_market: dict, typical: dict, cat_col, categories, labels, key,
                         sig=None):
    """Average move after each kind of event, in every market side by side."""
    horizon = st.segmented_control("Measured over", es.HORIZONS, default=5, key=f"{key}_xh",
                                   format_func=lambda h: HORIZON_NAMES[h].split(" (")[0]) or 5
    means, verdicts = mk.by_category(by_market, cat_col, categories, labels, horizon, sig)
    text = pd.DataFrame({k: [_cell(v, d) for v, d in zip(means[k], verdicts[k])]
                         for k in means.columns}, index=means.index)
    shades = pd.DataFrame({k: [_shade(v, typical[horizon][k], d)
                               for v, d in zip(means[k], verdicts[k])]
                           for k in means.columns}, index=means.index)
    typical_row = "Typical move at any time (±)"
    text.loc[typical_row] = [f"±{typical[horizon][k]:.1f}%" for k in means.columns]
    shades.loc[typical_row] = "color: #898781; font-style: italic"
    st.dataframe(text.style.apply(lambda _: shades, axis=None), width="stretch",
                 key=f"{key}_xtable",
                 column_config={k: st.column_config.Column(mk.MARKETS[k][1])
                                for k in means.columns})
    notes = " ".join(mk.NOTES[k] for k in means.columns if k in mk.NOTES)
    st.caption("Average move from the close before each event. Green = rose, red = fell; "
               "the stronger the colour, the bigger the move compared with that market's "
               f"typical move (bottom row). {LEGEND}. {notes}")


def market_reaction_table(by_market: dict, typical: dict, keep=None, key: str = "",
                          sig=None) -> None:
    """Compact table: how every market moved after one set of events."""
    table = mk.for_events(by_market, keep, sig)
    if table.empty:
        return
    shown = pd.DataFrame(index=table["market"])
    shown["Events"] = table["events"].astype(str).values
    shades = pd.DataFrame("", index=shown.index, columns=["Events"])
    for h, name in zip(es.HORIZONS, ["1 day", "1 week", "1 month"]):
        verdict = table[f"verdict_{h}"] if sig is not None else ["strong"] * len(table)
        shown[name] = [_cell(v, d) for v, d in zip(table[f"day_{h}_pct"], verdict)]
        shades[name] = [_shade(v, typical[h][k], d) for v, k, d in
                        zip(table[f"day_{h}_pct"], table["key"], verdict)]
    shown["Rose after a week"] = [f"{v:.0f}%" for v in table["pct_up_5"]]
    shown["Typical week (any time)"] = [f"±{typical[5][k]:.1f}%" for k in table["key"]]
    shades = shades.reindex(columns=shown.columns, fill_value="")
    st.dataframe(shown.style.apply(lambda _: shades, axis=None), width="stretch",
                 key=f"{key}_mtable", column_config={"market": st.column_config.Column("Market")})
    if sig is not None:
        st.caption(LEGEND + ".")
