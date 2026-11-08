"""
Shared look and building blocks for every page of the website:
the page styling, chart styling, and the event-study sections reused by the
News, EIA, OPEC+ and Fed pages.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import event_study as es

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


def topic_picker(label: str, options: list, labels: dict, colors: dict, key: str,
                 default=None, none_text: str = "") -> str | None:
    """A compact button that opens a panel of chips, each in its topic's own
    colour (Streamlit menus can only show plain text, so the chips are
    coloured here with CSS, by their position in the group). The current
    choice is shown as a chip beside the button."""
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
    right.markdown(chip(labels[chosen], colors[chosen]) if chosen else
                   f'<span style="color:#898781">{none_text}</span>', unsafe_allow_html=True)
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
def comparison_section(prices, results, paths, cat_col, categories, labels, colors, key):
    """Average Brent path for every category, plus a summary table.
    (A fragment: changing its options only redraws this section.)"""
    fig = go.Figure()
    for cat in categories:
        dates = results.loc[results[cat_col] == cat, "date"]
        if dates.empty:
            continue
        avg = average_path(paths, dates)
        fig.add_trace(go.Scatter(
            x=avg.index, y=avg.values, mode="lines", name=f"{labels[cat]} ({len(dates)})",
            line=dict(color=colors[cat], width=2.5), hovertemplate="%{y:+.1f}%"))
    st.plotly_chart(style_event_chart(fig, "Average % change in Brent"), width="stretch",
                    key=f"{key}_avg_chart")

    horizon = st.segmented_control("Measure the change after", es.HORIZONS, default=1,
                                   format_func=lambda h: HORIZON_NAMES[h].split(" (")[0],
                                   key=f"{key}_horizon") or 1
    col = f"day_{horizon}_pct"
    summary = (results.groupby(cat_col)[col]
               .agg(events="count", average="mean", median="median",
                    pct_up=lambda s: (s > 0).mean() * 100, best="max", worst="min")
               .reindex(categories).dropna(how="all"))
    summary.index = [labels[c] for c in summary.index]
    st.dataframe(summary, width="stretch", key=f"{key}_summary", column_config={
        "events": st.column_config.NumberColumn("Events"),
        "average": st.column_config.NumberColumn("Average", format=PCT),
        "median": st.column_config.NumberColumn("Median", format=PCT),
        "pct_up": st.column_config.NumberColumn("Times price rose", format="%.0f%%"),
        "best": st.column_config.NumberColumn("Best", format=PCT),
        "worst": st.column_config.NumberColumn("Worst", format=PCT),
    })
    st.caption(f"For comparison: on any ordinary day, Brent's typical move over "
               f"{HORIZON_NAMES[horizon]} is about ±{es.typical_move(prices, horizon):.1f}%. "
               "Results smaller than that may just be normal noise.")


@st.fragment
def drilldown_section(results, paths, cat_col, categories, labels, colors,
                      table_columns, key, select_label="Category"):
    """Pick one category: each event (or the spread, if many) + a table."""
    cat = st.selectbox(select_label, categories, format_func=lambda c: labels[c],
                       key=f"{key}_select")
    group = results[results[cat_col] == cat]
    event_paths(group, paths, colors[cat], table_columns, key)


def event_paths(group, paths, color, table_columns, key) -> None:
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
    fig = style_event_chart(fig, "% change in Brent")
    fig.update_layout(hovermode="closest" if len(group) <= 60 else "x unified")
    st.plotly_chart(fig, width="stretch", key=f"{key}_drill_chart")
    st.caption(note)
    st.dataframe(group[list(table_columns)], width="stretch", hide_index=True,
                 key=f"{key}_events", column_config=table_columns)
